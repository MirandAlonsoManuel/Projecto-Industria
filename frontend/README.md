# Camera Detection IA - Frontend

Frontend del sistema web de visión mediante técnicas de Machine Learning (ML). (base)

## Tecnologías

* React
* TypeScript
* Vite
* React Compiler
* ESLint

## Requisitos

* Node.js (versión recomendada: 20.x o superior)
* npm (incluido con Node.js)

## Instalación

Clonar el repositorio:

```bash
git clone <url-del-repositorio>
cd <nombre-del-proyecto>
```

Instalar las dependencias:

```bash
npm install
```

## Desarrollo

Iniciar el servidor de desarrollo:

```bash
npm run dev
```

La aplicación estará disponible en:

```text
http://localhost:5173
```

## Scripts Disponibles

### Iniciar entorno de desarrollo

```bash
npm run dev
```

### Generar build de producción

```bash
npm run build
```

### Visualizar build localmente

```bash
npm run preview
```

### Ejecutar linting

```bash
npm run lint
```

## Estructura del Proyecto

```text
src/
├── assets/
├── components/
├── pages/
├── services/
├── hooks/
├── types/
├── App.tsx
└── main.tsx
```

> La estructura podrá evolucionar conforme crezcan los requerimientos del proyecto.

## Variables de Entorno

Crear un archivo `.env` basado en `.env.example`.

Ejemplo:

```env
VITE_API_URL=http://localhost:3000
```

Las variables accesibles desde el cliente deben comenzar con el prefijo `VITE_`.

## Convenciones

* Utilizar TypeScript para todo el código nuevo.
* Mantener componentes pequeños y reutilizables.
* Ejecutar ESLint antes de crear un Pull Request.
* Seguir la estructura de carpetas definida por el equipo.

## Licencia

Este proyecto está distribuido bajo la licencia especificada en el archivo `LICENSE`.
