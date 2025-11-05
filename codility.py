# you can write to stdout for debugging purposes, e.g.
# print("this is a debug message")

def solution(A):
    # Implement your solution here
    numeros = set(A)
    print(numeros)
    menor_faltante = 1

    while menor_faltante in numeros:
        print(menor_faltante)
        menor_faltante += 1
        print(menor_faltante)
        
    return menor_faltante

numeros = [1, 3, 6, 4, 1, 2]
print(solution(numeros)) 

