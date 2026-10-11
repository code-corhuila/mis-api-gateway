# mis-api-gateway

Entrada unica de MediStock (Medicine Inventory System), HU-OPS-001. Nginx 1.30.5 en contenedor sin privilegios, sistema de archivos de solo lectura y temporales en tmpfs. No contiene claves privadas, cuentas ni una base de datos.

## Alcance

| Ruta | Destino | Seguridad |
| --- | --- | --- |
| /health | Estado propio del gateway | Publico, independiente de los dominios |
| /api/v1/auth/login | mis-security | Credenciales verificadas por Seguridad |
| /api/v1/auth/jwks | mis-security | Claves publicas |
| /api/v1/auth/me | mis-security | Bearer requerido |
| /api/v1/medications y /{id} | Catalogo | Bearer requerido |
| /api/v1/suppliers y /{id} | Proveedores | Bearer requerido |
| /api/v1/entries, /{id}, /{id}/activate y /{id}/cancel | Inventario | Bearer requerido |

El gateway solo comprueba presencia de Bearer. Cada API valida firma RS256, claims y permisos; un token arbitrario no autentica al usuario. Se eliminan X-User-Id y X-User-Role antes de reenviar. URI, consulta e Idempotency-Key se conservan, sin reintentar escrituras automaticamente.

## Arranque

Docker Desktop con contenedores Linux, conexion para la primera construccion y PowerShell 7. Las carpetas de infraestructura, identidad, Catalogo y Proveedores deben estar disponibles como hermanas. Las piezas locales de dominio aun necesitan publicacion oficial.

```powershell
cd "D:\descargas\pago 2\mis-infra-postgres"
pwsh -NoProfile -File .\scripts\Start-Gateway.ps1
pwsh -NoProfile -File .\scripts\Test-Gateway.ps1
```

Direccion inicial http://localhost:8080. Start-Gateway genera env/dev.env solo si falta, con puerto 8080 y origenes http://localhost:4200,http://localhost:5173; conserva configuracion existente. Si el puerto esta ocupado, cambiar GATEWAY_HOST_PORT localmente, no detener procesos ajenos. Docker y los datos no dependen de instalar Java o Python en el equipo.

compose.gateway.yml es la raiz del sistema integrado. Seguridad, Catalogo y Proveedores no publican puertos al host; solo el gateway publica las APIs. PostgreSQL y MongoDB conservan puertos locales de administracion. No ejecutar raices anteriores simultaneamente para el mismo ambiente. Para diagnostico directo, usar explicitamente las composiciones .dev anteriores y volver despues a Start-Gateway.

En Postman, configurar baseUrl y securityUrl de las colecciones existentes con la direccion del gateway. Los puertos 58081/58082/58083 no estan disponibles mientras se usa esta raiz. Login, consultas y creaciones conservan sus contratos y Location relativa.

## Politicas

GATEWAY_ALLOWED_ORIGINS es una lista explicita separada por comas, sin espacios, rutas ni wildcard. HTTP/HTTPS, host y puerto opcional; IPv6 literal no incluido en este validador inicial. Se rechazan origenes no autorizados. Preflight admite GET, POST y HEAD sin token, para rutas conocidas. Permite Authorization, Content-Type, Idempotency-Key y X-Correlation-Id; expone Location, X-Correlation-Id y Retry-After. No utiliza cookies ni Access-Control-Allow-Credentials.

Diez solicitudes por segundo y por IP real del peer, burst 20. X-Forwarded-For del cliente no se confia. Exceso devuelve 429 TOO_MANY_REQUESTS con Retry-After=1. La salud y los rechazos locales tempranos no consumen el limite de solicitudes reenviadas. Configuracion basada en el [modulo oficial limit_req](https://nginx.org/en/docs/http/ngx_http_limit_req_module.html).

Correlacion valida se conserva; si falta se genera UUID y, si es invalida, se devuelve 400 con nueva correlacion segura. Se entrega una sola cabecera incluso si la API tambien la devuelve. Errores propios usan error, message y traceId; errores de negocio de las APIs se conservan sin reemplazarlos.

Cuerpo maximo 64 KiB; cabeceras 5 segundos, cuerpo y escritura 15, keep-alive 30 y apagado ordenado 20. Conexion upstream 2 segundos y espera de lectura 10. Los timeouts de Nginx son limites de inactividad, no una promesa de plazo total para todos los casos. No se afirma cumplimiento completo de requisitos no funcionales del release.

Resolucion DNS de Docker con renovacion, sin depender de IPs fijas. Fallo o timeout de un upstream produce 503 SERVICE_UNAVAILABLE solo en su ruta; la salud propia y otros dominios siguen disponibles. Auditoria JSON sin Authorization, cuerpos o query string. Configuracion basada en el [proxy oficial Nginx](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

## Pruebas y entrega

```powershell
cd "D:\descargas\pago 2\mis-api-gateway"
python tests/test_gateway.py
```

Doce pruebas con upstreams sinteticos en proyecto Docker desechable; no prueban firmas JWT. Test-Gateway comprueba identidad y roles reales, creacion e idempotencia en ambos motores, CORS, correlacion y ausencia de puertos directos. Conserva un medicamento y un proveedor sinteticos por corrida.

Rama hu-ops-001-gateway-dev desde develop y PR hacia develop dentro de code-corhuila/mis-api-gateway. CI solo en PR develop/qa, con cancelacion y limite de 10 minutos. QA recibe cherry-pick -x; main requiere aprobacion del docente. Preservar CODEOWNERS.

Pendientes: publicar las piezas locales de dominio, integrar frontend y las restantes HU de Inventario, definir TLS para un despliegue no local, promover a QA y registrar evidencias centrales. El puerto actual se enlaza solo a 127.0.0.1. Esta entrega no cierra HU-OPS-001 completa.

## Evidencia local - 2026-10-10

Ocho pruebas aisladas aprobadas: rutas, Bearer, CORS, correlacion, cuerpo, configuracion invalida, aislamiento de fallo/timeout y 429 con Retry-After. Se eliminaron los contenedores y red de prueba al terminar, sin tocar desarrollo.

Aceptacion real aprobada con Seguridad, PostgreSQL y MongoDB: login de cuatro roles, escritura exclusiva de ADMIN, consultas, Location e idempotencia conservadas en los dos dominios. Composicion comprobada sin puertos directos de las APIs; gateway saludable en localhost:8080. CI de este PR y promocion a QA/main siguen pendientes.

Documentacion central: [mis-docs](https://github.com/code-corhuila/mis-docs).

## Consultas de Inventario - HU-INV-002

Las rutas exactas /api/v1/stock y /api/v1/movements reenvian al mismo backend interno inventory:8080, conservando query string, JWT y correlacion. No se habilitan subrutas arbitrarias ni puertos directos. Los permisos y filtros se validan en Inventario. La prueba aislada comprueba rutas y autenticacion presente; Test-InventoryRead.ps1 en infraestructura valida stock e historial con roles y datos reales sinteticos.

## Salidas de Inventario - HU-INV-003

/api/v1/exits y /api/v1/exits/{id} se reenvian a inventory:8080. No se admiten subrutas de cancelacion ni puertos directos. La API controla permisos, stock, vencimiento e idempotencia; el gateway conserva Authorization, Idempotency-Key y correlacion. Test-InventoryExits.ps1 verifica las reglas contra PostgreSQL real con datos sinteticos.

## Recepciones de Proveedores - HU-WFL-001

/api/v1/receipts, consulta por UUID y confirm/void se reenvian a suppliers:8080. No se admiten subrutas arbitrarias. La API exige identidad de workflow firmada para escribir; el gateway no interpreta el claim service ni confia en X-Service. Esta ampliacion no agrega aun las rutas del orquestador de sagas.

## Integracion de Inventario - HU-INV-001

La rama hu-inv-001-dev agrega /api/v1/entries, consulta por UUID y las transiciones activate/cancel hacia el backend inventory:8080. Solo reenvia credenciales: la API verifica JWT y permisos. El backend y sus migraciones se prepararon localmente, pendientes de repositorios oficiales.

Para incluir Inventario ejecutar scripts/Start-Inventory.ps1 desde mis-infra-postgres y administrar el ambiente con compose.inventory.yml. Start-Gateway y compose.gateway.yml corresponden al alcance anterior sin Inventario; no mezclar raices para administrar el mismo proyecto.

Evidencia local, 2026-10-10: nueve pruebas aisladas del gateway correctas, incluidas las nuevas rutas; aceptacion real de Inventario con permisos, idempotencia y concurrencia correcta. Este avance no acredita publicacion de dominios ni QA formal.
