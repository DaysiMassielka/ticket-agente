# RB-03 · Reserva sin confirmar

## Síntomas
El cliente reservó y pagó pero no recibe el correo de confirmación, o su reserva sigue en estado pendiente en la web.

## Diagnóstico
Cruzar la reserva con sus pagos. Una reserva pendiente con un pago cobrado indica una confirmación perdida: el cobro se hizo pero el sistema no la confirmó. Una reserva pendiente con un pago pendiente significa que el pago todavía no se ha completado.

```sql
SELECT r.id AS reserva_id, r.estado AS estado_reserva, p.id AS pago_id, p.estado AS estado_pago, p.importe, p.creado_en FROM reservas r LEFT JOIN pagos p ON p.reserva_id = r.id WHERE r.id = :reserva
```

## Solución
Si el pago está pendiente, explicar al cliente que la reserva se confirma sola cuando el banco confirme el pago, hasta 24 horas después, y que no tiene que hacer nada.

## Cuándo escalar
Si la reserva está pendiente y el pago está cobrado, escalar a Desarrollo con prioridad P2 para reprocesar la confirmación: el cliente ha pagado y no tiene su servicio.
