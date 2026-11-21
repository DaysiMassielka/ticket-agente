# RB-04 · Errores 5xx en la API de pagos

## Síntomas
Los clientes ven un error del servidor al pagar, la pantalla del checkout se queda en blanco o el cobro falla una y otra vez. Hay códigos 500 o 502 en el log de la API.

## Diagnóstico
Contar en logs_api los errores de código 500 o superior sobre el endpoint de cobro. Unos pocos errores aislados no son una incidencia. Muchos errores seguidos en pocos minutos indican que la pasarela de pago está caída.

```sql
SELECT codigo, COUNT(*) AS total, MIN(creado_en) AS desde, MAX(creado_en) AS hasta FROM logs_api WHERE endpoint = '/api/pagos/cobrar' AND codigo >= 500 GROUP BY codigo
```

## Solución
Si hay menos de 5 errores, pedir al cliente que reintente el pago pasados unos minutos.

## Cuándo escalar
Con 5 o más errores 5xx en el endpoint de cobro es una incidencia crítica con prioridad P1: avisar de inmediato a Desarrollo de guardia, porque se están perdiendo cobros de todos los clientes.
