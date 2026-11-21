# RB-02 · Usuario sin acceso

## Síntomas
El usuario no puede iniciar sesión, ve el mensaje de acceso denegado o de cuenta bloqueada, o entra pero no ve su panel de gestión.

## Diagnóstico
Consultar la tabla usuarios por el correo del cliente y mirar el estado y el rol. El estado bloqueado_intentos significa que la cuenta se bloqueó por intentos fallidos de contraseña. Un rol vacío significa que el usuario no tiene permisos asignados.

```sql
SELECT id, email, estado, rol, ultimo_acceso FROM usuarios WHERE email = :email
```

## Solución
Si la cuenta está bloqueada por intentos, indicar al cliente que use la opción Olvidé mi contraseña: el bloqueo se levanta al restablecerla, en unos 30 minutos.

## Cuándo escalar
Si el usuario no tiene rol asignado, escalar a Administración de accesos con prioridad P3: cambiar un rol requiere la aprobación de un administrador. Soporte nunca cambia roles ni permisos.
