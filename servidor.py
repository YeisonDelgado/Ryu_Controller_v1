from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import paramiko
from fastapi.middleware.cors import CORSMiddleware
import httpx
import socket
from typing import Optional, Dict
import logging
import asyncio
from pydantic import BaseModel

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SDN Controller Interface")

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de red
RYU_SERVER_IP = "10.52.155.226"
MININET_SERVER_IP = "10.52.155.234"
RYU_SERVER_PORT = 8080
RYU_BASE_URL = f"http://{RYU_SERVER_IP}:{RYU_SERVER_PORT}"

# Credenciales
RYU_USER = "ryoyeison"
RYU_PASS = "12345"
MININET_USER = "mininet"  # Ajusta según tus credenciales
MININET_PASS = "mininet"  # Ajusta según tus credenciales

# Estado global de los servicios
service_status = {
    "ryu": False,
    "mininet": False,
    "ryu_app": None,
    "mininet_topology": None
}

class ServiceStatus(BaseModel):
    ryu: bool
    mininet: bool
    ryu_app: Optional[str]
    mininet_topology: Optional[str]

# Configuración de timeouts
SSH_TIMEOUT = 10
HTTP_TIMEOUT = 5

async def check_host_availability(host: str, port: int, timeout: int = 5) -> bool:
    """Verifica si un host está disponible"""
    try:
        _, writer = await asyncio.open_connection(host, port)
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False

async def ssh_connect(host: str, username: str, password: str) -> paramiko.SSHClient:
    """Establece una conexión SSH"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=host,
            username=username,
            password=password,
            timeout=10
        )
        return ssh
    except Exception as e:
        logger.error(f"Error connecting to {host}: {str(e)}")
        raise HTTPException(status_code=503, detail=f"No se puede conectar a {host}: {str(e)}")

@app.get("/status")
async def get_status() -> ServiceStatus:
    """Obtiene el estado actual de los servicios"""
    return ServiceStatus(**service_status)

# Variable para almacenar el proceso de Ryu
ryu_process = None

class StartAppRequest(BaseModel):
    app_name: str
    topology_file: Optional[str] = "nsfnet.py"

@app.post("/start-all")
async def start_all(request: StartAppRequest):
    """Inicia tanto Ryu como Mininet con la configuración especificada"""
    global service_status
    
    try:
        # Detener servicios existentes primero
        try:
            await stop_all()
        except Exception as e:
            logger.warning(f"Error al detener servicios existentes: {str(e)}")

        # Verificar conexión a ambos servidores
        ryu_available = await check_host_availability(RYU_SERVER_IP, 22)
        mininet_available = await check_host_availability(MININET_SERVER_IP, 22)

        if not ryu_available or not mininet_available:
            raise HTTPException(
                status_code=503,
                detail="No se puede conectar a uno o ambos servidores"
            )

        # 1. Iniciar Ryu primero
        ssh_ryu = await ssh_connect(RYU_SERVER_IP, RYU_USER, RYU_PASS)
        
        # Comando para iniciar Ryu
        if request.app_name == "topologia":
            ryu_command = "ryu-manager --verbose --observe-links /usr/lib/python3/dist-packages/ryu/app/simple_switch_13.py /usr/lib/python3/dist-packages/ryu/app/rest_topology.py"
        else:
            ryu_command = f"ryu-manager /home/ryoyeison/Proyecto_Final/{request.app_name}"
        
        # Matar cualquier proceso ryu-manager existente
        ssh_ryu.exec_command("pkill -f ryu-manager")
        await asyncio.sleep(2)  # Esperar a que termine el proceso anterior
        
        # Iniciar Ryu en background
        stdin, stdout, stderr = ssh_ryu.exec_command(
            f"nohup {ryu_command} > ryu.log 2>&1 &"
        )
    
        # Esperar un momento para que Ryu inicie
        await asyncio.sleep(5)
        
        # 2. Iniciar Mininet
        ssh_mininet = await ssh_connect(MININET_SERVER_IP, MININET_USER, MININET_PASS)
        
        # Comando para iniciar Mininet
        mininet_command = f"sudo python3 {request.topology_file} {RYU_SERVER_IP}"
        
        stdin, stdout, stderr = ssh_mininet.exec_command(
            f"nohup {mininet_command} > mininet.log 2>&1 &"
        )
        
        # Actualizar estado
        service_status.update({
            "ryu": True,
            "mininet": True,
            "ryu_app": request.app_name,
            "mininet_topology": request.topology_file
        })
        
        return {"message": "Servicios iniciados correctamente", "status": service_status}
        
    except Exception as e:
        logger.error(f"Error al iniciar servicios: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al iniciar servicios: {str(e)}")

@app.post("/start-ryu")
async def start_ryu(request: Request):
    """Inicia solo el controlador Ryu"""
    global service_status
    try:
        # Verificar si el servidor Ryu está accesible
        if not await check_host_availability(RYU_SERVER_IP, 22):
            raise HTTPException(
                status_code=503,
                detail=f"No se puede conectar al servidor Ryu en {RYU_SERVER_IP}"
            )

        data = await request.json()
        app_name = data.get('app_name')
        
        logger.info(f"Iniciando aplicación Ryu: {app_name}")
        
        ssh = await ssh_connect(RYU_SERVER_IP, RYU_USER, RYU_PASS)

        # Ejecutar el comando ryu-manager con el app 'simple_switch.py'
        #command = "ryu-manager /usr/lib/python3/dist-packages/ryu/app/simple_switch.py"
        if(app_name=="topologia"):
            command = "ryu-manager --verbose --observe-links /usr/lib/python3/dist-packages/ryu/app/simple_switch_13.py /usr/lib/python3/dist-packages/ryu/app/rest_topology.py"
            
        else:
            command = f"ryu-manager /usr/lib/python3/dist-packages/ryu/app/{app_name}"
        
        ryu_process = ssh.exec_command(command, get_pty=True)  # Ejecuta el comando y obtiene el canal
        # Acceder al canal de stdin y stdout
        stdin, stdout, stderr = ryu_process

        return JSONResponse({"message": "Aplicación iniciada correctamente"})
    except Exception as e:
        return JSONResponse({"message": f"Error al iniciar la aplicación: {str(e)}"}, status_code=500)

@app.post("/stop-all")
async def stop_all():
    """Detiene tanto Ryu como Mininet"""
    global service_status
    try:
        # Detener Mininet primero
        if service_status["mininet"]:
            ssh_mininet = await ssh_connect(MININET_SERVER_IP, MININET_USER, MININET_PASS)
            ssh_mininet.exec_command("sudo mn -c")  # Limpia Mininet
            ssh_mininet.exec_command("sudo pkill -f mininet")
            ssh_mininet.close()
            
        # Detener Ryu
        if service_status["ryu"]:
            ssh_ryu = await ssh_connect(RYU_SERVER_IP, RYU_USER, RYU_PASS)
            ssh_ryu.exec_command("pkill -f ryu-manager")
            ssh_ryu.close()
            
        # Actualizar estado
        service_status.update({
            "ryu": False,
            "mininet": False,
            "ryu_app": None,
            "mininet_topology": None
        })
        
        return {"message": "Servicios detenidos correctamente", "status": service_status}
        
    except Exception as e:
        logger.error(f"Error al detener servicios: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al detener servicios: {str(e)}")

@app.post("/stop-ryu")
async def stop_ryu():
    """Detiene solo el controlador Ryu"""
    global service_status
    try:
        if service_status["ryu"]:
            ssh = await ssh_connect(RYU_SERVER_IP, RYU_USER, RYU_PASS)
            ssh.exec_command("pkill -f ryu-manager")
            ssh.close()
            
            service_status["ryu"] = False
            service_status["ryu_app"] = None
            
            return JSONResponse({"message": "Ryu detenido correctamente", "status": service_status})
        else:
            return JSONResponse({"message": "Ryu no está en ejecución"}, status_code=400)
    except Exception as e:
        logger.error(f"Error al detener Ryu: {str(e)}")
        return JSONResponse({"message": f"Error al detener Ryu: {str(e)}"}, status_code=500)

@app.get("/v1.0/topology/links")
async def get_links():
    """
    Método para obtener la lista de enlaces de la topología desde el controlador Ryu.
    """
    try:
        if not service_status["ryu"]:
            raise HTTPException(
                status_code=503,
                detail="El controlador Ryu no está en ejecución"
            )

        # Verificar la disponibilidad del servidor Ryu
        if not await check_host_availability(RYU_SERVER_IP, RYU_SERVER_PORT):
            raise HTTPException(
                status_code=503,
                detail=f"No se puede conectar al servidor Ryu en {RYU_SERVER_IP}:{RYU_SERVER_PORT}"
            )

        url = f"{RYU_BASE_URL}/v1.0/topology/links"
        timeout = httpx.Timeout(HTTP_TIMEOUT)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    except httpx.RequestError as e:
        # Capturar errores de conexión o solicitud
        raise HTTPException(status_code=500, detail=f"Error al conectar con el controlador Ryu: {e}")
    except httpx.HTTPStatusError as e:
        # Capturar errores de respuesta HTTP (como 404 o 500)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Error desde el controlador Ryu: {e.response.text}"
        ) 

@app.get("/v1.0/topology/hosts")
async def get_hosts():
    """
    Método para obtener la lista de hosts de la topología desde el controlador Ryu.
    """
    try:
        if not service_status["ryu"]:
            raise HTTPException(
                status_code=503,
                detail="El controlador Ryu no está en ejecución"
            )

        # Verificar la disponibilidad del servidor Ryu
        if not await check_host_availability(RYU_SERVER_IP, RYU_SERVER_PORT):
            raise HTTPException(
                status_code=503,
                detail=f"No se puede conectar al servidor Ryu en {RYU_SERVER_IP}:{RYU_SERVER_PORT}"
            )

        # URL del endpoint de hosts en Ryu
        url = f"{RYU_BASE_URL}/v1.0/topology/hosts"

        # Configurar timeout
        timeout = httpx.Timeout(timeout=HTTP_TIMEOUT)

        # Hacer una solicitud GET asincrónica al controlador Ryu
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()  # Levanta una excepción si el código de estado no es 2xx
            return response.json()  # Devolver la respuesta como JSON

    except httpx.RequestError as e:
        # Capturar errores de conexión o solicitud
        raise HTTPException(status_code=500, detail=f"Error al conectar con el controlador Ryu: {e}")
    except httpx.HTTPStatusError as e:
        # Capturar errores de respuesta HTTP (como 404 o 500)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Error desde el controlador Ryu: {e.response.text}"
        )


@app.post("/stats/flowentry/add")
async def agregar_flujo(request: Request):
    """
    Método para agregar una entrada de flujo en el controlador Ryu.
    """
    try:
        # Obtener el JSON enviado por el cliente
        payload = await request.json()

        # URL del endpoint en el servidor Ryu
        url = f"{RYU_BASE_URL}/stats/flowentry/add"

        # Enviar la solicitud POST al controlador Ryu
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

            # Intentar parsear la respuesta como JSON
            try:
                response_data = response.json()
            except ValueError:
                response_data = {"raw_response": response.text}

            return {
                "message": "Solicitud procesada con éxito en Ryu",
                "ryu_response": response_data,
            }

    except httpx.RequestError as e:
        # Capturar errores de conexión o solicitud
        raise HTTPException(status_code=500, detail=f"Error al conectar con el controlador Ryu: {e}")
    except httpx.HTTPStatusError as e:
        # Capturar errores de respuesta HTTP (como 404 o 500)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Error desde el controlador Ryu: {e.response.text}"
        )
    except Exception as e:
        # Capturar otros errores internos
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


@app.post("/routing/mode")
async def set_routing_mode(request: Request):
    """Proxy endpoint to set routing mode on the Ryu routing app.
    Expects JSON: { "mode": "dijkstra_bw" | "shortest_hops" }
    """
    try:
        payload = await request.json()
        url = f"{RYU_BASE_URL}/routing/mode"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            try:
                return response.json()
            except ValueError:
                return {"raw": response.text}
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con Ryu: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Error desde Ryu: {e.response.text}")


@app.get("/routing/status")
async def get_routing_status():
    """Proxy to Ryu routing status endpoint."""
    try:
        if not service_status["ryu"]:
            raise HTTPException(
                status_code=503,
                detail="El controlador Ryu no está en ejecución"
            )

        # Verificar la disponibilidad del servidor Ryu
        if not await check_host_availability(RYU_SERVER_IP, RYU_SERVER_PORT):
            raise HTTPException(
                status_code=503,
                detail=f"No se puede conectar al servidor Ryu en {RYU_SERVER_IP}:{RYU_SERVER_PORT}"
            )

        url = f"{RYU_BASE_URL}/routing/status"
        timeout = httpx.Timeout(timeout=HTTP_TIMEOUT)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Error al conectar con Ryu: {e}")
        raise HTTPException(status_code=500, detail=f"Error al conectar con Ryu: {e}")
    except httpx.HTTPStatusError as e:
        logger.error(f"Error desde Ryu: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Error desde Ryu: {e.response.text}")
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error inesperado: {str(e)}")