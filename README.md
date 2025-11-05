# Controlador Ryu — Proyecto para la tarea de Forwarding/Control/Application/Management planes

Resumen
-------
Este repositorio contiene un proyecto de ejemplo que implementa los componentes solicitados del siguiente requerimiento:

- Forwarding plane: Topología NSFNET simulada con Mininet (`mininet_nsfnnet.py`) usando Open vSwitch (TCLink con bw).
- Control plane: Ryu como controlador SDN (app incluida `ryu_routing_app.py`).
- Application plane: aplicación Ryu que calcula rutas con NetworkX (Dijkstra con peso 1/bandwidth y shortest path por hops) e instala flujos proactivamente (esqueleto).
- Management plane: API FastAPI (`servidor.py`) y UI (`aplicacion.html`) para iniciar apps, elegir algoritmo de routing y monitorizar estado.

Importante
----------
- El entorno de ejecución recomendado es Linux (Ubuntu) o WSL2 con un kernel completo. Mininet y Open vSwitch funcionan mejor en Linux nativo.
- Para la demo local es conveniente ejecutar Ryu y Mininet en la misma máquina/VM.

Requisitos
----------
- Python 3.8+
- Mininet (recomendado instalar con apt: `sudo apt-get install mininet`) o desde fuente
- Open vSwitch (suele venir con Mininet)
- Ryu (pip install ryu) — algunas distribuciones requieren instalar desde repositorio

Dependencias Python
-------------------
Instala las dependencias listadas en `requirements.txt`. En Linux/WSL2:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Nota: Mininet es preferible instalarlo por apt para evitar problemas.

Cómo ejecutar (pasos recomendados)
---------------------------------
1. Arranca Ryu con la app de routing (en Linux/VM):

```bash
# desde la carpeta del proyecto
ryu-manager ryu_routing_app.py &
```

Ryu expondrá su API REST (WSGI) en el puerto por defecto (por lo general 8080). Si usas una configuración distinta, actualiza `servidor.py` RYU_SERVER_IP/PORT.

2. Arranca Mininet con la topología NSFNET:

```bash
python3 mininet_nsfnnet.py
```

La topología crea 14 switches y 14 hosts (h1..h14), y conecta un RemoteController apuntando a `127.0.0.1:6633`.

3. Arranca el backend FastAPI (puedes usar la máquina host o otra terminal):

```bash
uvicorn servidor:app --host 0.0.0.0 --port 8000 --reload
```

4. Sirve el frontend o ábrelo localmente:

```bash
# opción simple: servir con http.server
python3 -m http.server 5500
# abrir http://localhost:5500/aplicacion.html
```

Flujo de la demo
-----------------
1. En la UI selecciona "App para topologia" y pulsa "Iniciar Aplicación" si quieres controlar una app Ryu remota (esta app está pensada para arrancar Ryu vía SSH si lo deseas). Para una demo local, arranca Ryu localmente con `ryu-manager ryu_routing_app.py`.
2. En la sección Application Plane elige el algoritmo (Dijkstra 1/bandwidth o Shortest-hop) y pulsa "Aplicar Algoritmo" — esto llamará al endpoint `/routing/mode` del backend, que a su vez proxyará la petición al app Ryu. La app Ryu calculará rutas y (esqueleto) instalará flujos proactivamente.
3. Usa Mininet CLI para generar tráfico entre hosts (por ejemplo `h1 ping h2` o `iperf`) y observa cambios en la topología o métricas.

Notas y siguientes pasos
-----------------------
- El código de `ryu_routing_app.py` es un esqueleto funcional que construye el grafo con `networkx` y expone endpoints REST. Para un despliegue real se recomienda completar:
  - Mapeo real de puertos entre switches (para determinar `out_port` en `_port_to_neighbor`).
  - Uso de los objetos Datapath de Ryu para enviar OFPFlowMod y reglas completas (match por IP/MAC, timeouts, prioridad).
  - Manejo de fallos y recalculado automático sobre eventos de link/switch down.
- Diagrama de arquitectura, despliegue y secuencias deben añadirse como artefactos gráficos para la sustentación (puedes crearlos con draw.io o similar y colocarlos en `docs/`).

Contribuir
---------
Si quieres que yo implemente las partes pendientes (instalación real de flujos OF v1.3, mapeo de puertos desde la topología, y ejemplos de monitorización), indícalo y lo hago en el repo.
