# RB-05 · Reembolso pendiente

## Síntomas
El cliente canceló su reserva y todavía no ve la devolución del dinero, o pregunta cuándo le llegará el reembolso.

## Diagnóstico
Buscar el pago de la reserva en estado reembolso_en_proceso y mirar desde cuándo se solicitó. El plazo de un reembolso es de 5 días hábiles desde la solicitud, unos 7 días naturales.

```sql
SELECT id, reserva_id, importe, estado, referencia, creado_en FROM pagos WHERE reserva_id = :reserva
```

## Solución
Si el reembolso está en proceso y dentro de plazo, informar al cliente de que el dinero llegará como máximo en 5 días hábiles desde la solicitud y que no hace falta hacer nada más.

## Cuándo escalar
Si el reembolso lleva en proceso más de 7 días naturales, escalar a Finanzas con prioridad P3 para revisarlo con el banco.
