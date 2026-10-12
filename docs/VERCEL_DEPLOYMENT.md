# Web Vercel y radar independiente del PC

Estado: código preparado y comprobaciones locales. No publicado; sin cuenta Vercel
conectada ni servidor continuo provisionado en esta sesión.

## Arquitectura

`web_vercel/` es un proyecto Vercel independiente: página responsive de Bollinger,
resultados y últimas detecciones. Su función `/api/dashboard` protege la consulta
con contraseña y una cookie firmada, HttpOnly, Secure, SameSite Strict y ocho horas
de duración. La clave del radar permanece en el servidor de Vercel, nunca en el JS.
La interfaz es de lectura: no incluye los controles locales de iniciar procesos,
credenciales de Telegram ni trading. No se afirma una migración de todas las
pestañas de Streamlit; el módulo operativo de Bollinger es el alcance preparado.

El radar continuo vive en un servidor Linux con Docker. Ejecuta el colector de
Alpaca en `--data-only`, el radar exclusivo de Bollinger, su estudio y una API
privada. Docker conserva SQLite e informes en un volumen; Caddy termina HTTPS.
El supervisor y Docker reinician procesos. El dashboard falla de forma explícita
si no responde ese radar; los datos atrasados no se muestran como señales vigentes.

No usar funciones de Vercel como un proceso infinito de recepción de mercado.
Hobby tiene 300 segundos de duración máxima por función y cron como máximo diario.
Por eso el paquete no configura un cron por minuto ni mantiene un radar mientras
alguien visita la página. Servicios/containers de Vercel siguen siendo unidades de
despliegue de funciones; no se presupone un servidor permanente gratuito.

## Publicar la pantalla

1. Crear/iniciar sesión en Vercel y conectar el repositorio autorizado.
2. Crear proyecto con **Root Directory: `web_vercel`**, framework **Other** y
   salida `public`. `vercel.json` declara la función Python; no hace falta Node
   para compilar la página estática.
3. Añadir las cuatro variables de `web_vercel/.env.example` en Vercel, mediante
   campos privados. Usar una contraseña privada de al menos 16 caracteres, un
   secreto independiente aleatorio de al menos 32 y una clave del radar de 32.
   El mismo `JJTRADE_BACKEND_KEY` va en Vercel y en el servidor del radar.
4. Publicar y probar el acceso privado. Sin `JJTRADE_BACKEND_URL` válido, la
   pantalla informa que falta conectar el radar; no simula mercado en vivo.

No subir todo `exports/` ni claves al repositorio. No iniciar un plan de pago
sin autorización. Verificar elegibilidad y límites del plan de la cuenta.

## Preparar el servidor continuo

1. Obtener un servidor adecuado y un nombre DNS que apunte a su IP. La existencia
   de código preparado no significa que una plaza gratuita esté disponible.
2. Copiar el proyecto sin secretos/exports privados. Instalar Docker y Compose.
3. Copiar `deployment/.env.example` a `deployment/.env` y completar las variables
   privadamente. Proteger los permisos del archivo. La clave Telegram cifrada
   con DPAPI del PC no sirve en Linux: usar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`
   en el servidor. El token no se guarda en JSON ni se entrega a la web.
4. Ejecutar desde `deployment/`: `docker compose up -d --build`.
5. Abrir 80/443 para HTTPS, restringir SSH; no publicar el puerto interno 8080.
6. Configurar en Vercel `JJTRADE_BACKEND_URL=https://<RADAR_DOMAIN>/snapshot`.

El Dockerfile y Compose están preparados pero NO se ejecutaron aquí: Docker
no está disponible en esta sesión Windows. Validar construcción y reinicios en
el servidor antes de declarar el sistema listo para operar sin PC.

## Historial y continuidad

El servicio nuevo recupera 30 días de datos y usa la lista guardada, incluido AVGO.
Para conservar toda la base local, transferir una copia SQLite consistente mediante
el mecanismo de backup del proyecto al volumen remoto, antes de arrancar los
procesos. No copiar un archivo SQLite que esté siendo escrito sin realizar backup.
Conservar copias externas al servidor y probar restauración.

Evitar dos colectores de Alpaca simultáneos si el plan limita conexiones. Durante
la migración, coordinar el apagado del colector local con el encendido remoto.
Transferir los registros de deduplicación también evita volver a enviar avisos
ya emitidos. No detener la instalación local hasta verificar la remota.

Aceptación: acceso por HTTPS desde el teléfono; registro del radar actualizado;
recuperación tras reinicio; prueba Telegram autorizada desde el servidor; PC local
apagado y radar todavía activo. Hasta completar estas pruebas no se garantiza
independencia del PC.

Fuentes verificadas el 9 de octubre de 2026:
- https://vercel.com/docs/functions/limitations
- https://vercel.com/docs/cron-jobs/usage-and-pricing
- https://vercel.com/docs/functions/runtimes/python
