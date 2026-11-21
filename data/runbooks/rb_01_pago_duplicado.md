# RB-01 · Pago duplicado

## Síntomas
El cliente dice que le han cobrado dos veces la misma reserva, ve dos cargos en el extracto del banco o pide la devolución de un cobro repetido.

## Diagnóstico
Comprobar en la tabla pagos si la reserva tiene más de un pago en estado cobrado con la misma referencia. Un segundo pago en estado retenido es una retención temporal del banco, no un cobro.

```sql
SELECT id, reserva_id, importe, estado, referencia, creado_en FROM pagos WHERE reserva_id = :reserva ORDER BY creado_en
```

## Solución
Si solo hay un pago cobrado, explicar al cliente que el otro cargo es una retención que el banco libera en 3 a 5 días hábiles y que no se le va a cobrar dos veces. Si hay dos pagos cobrados con la misma referencia, el cobro duplicado es real.

## Cuándo escalar
Escalar a Finanzas con prioridad P2 cuando existan dos pagos cobrados con la misma referencia: hay que reembolsar el importe repetido. Adjuntar los ids de los pagos.
