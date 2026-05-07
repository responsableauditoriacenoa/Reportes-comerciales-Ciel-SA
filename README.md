# Reporting de Patentamientos

Aplicacion Streamlit para importar archivos comerciales, consolidar datos historicos y visualizar KPIs de patentamientos, facturacion, comisiones, cuenta H y suscripciones.

## Funcionalidades

- Importacion de archivos `.xlsx`, `.xls` y reportes exportados desde el sistema de gestion.
- Importacion de archivos `.txt` separados por punto y coma, con base historica persistente.
- Mapeo flexible de columnas para adaptar distintos formatos de Excel.
- Persistencia local en `data/reporting.db` o persistencia productiva en PostgreSQL usando `DATABASE_URL`.
- Actualizacion de duplicados por columnas clave, por defecto factura y matricula.
- Si una fila duplicada llega con informacion nueva o distinta, la base consolidada se actualiza.
- Dashboard con patentamientos, facturacion, facturas, registros y evolucion mensual.
- Descarga de la base consolidada en CSV.
- Historial de importaciones.
- Historial independiente para importaciones Excel y TXT.

## Instalacion

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecutar

```powershell
streamlit run app.py
```

## GitHub

Para iniciar el repositorio local:

```powershell
git init
git add .
git commit -m "Crear app de reporting de patentamientos"
```

Luego crea un repositorio vacio en GitHub y conecta el remoto:

```powershell
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git branch -M main
git push -u origin main
```

## PostgreSQL en Streamlit Cloud

Para que las importaciones queden persistentes entre reinicios de Streamlit Cloud, usa PostgreSQL.

1. Crea una base PostgreSQL en Neon, Supabase, Railway u otro proveedor.
2. Copia la connection string en formato:

```text
postgresql://usuario:password@host:puerto/base?sslmode=require
```

3. En Streamlit Cloud, entra en `Settings` > `Secrets` y agrega:

```toml
DATABASE_URL = "postgresql://usuario:password@host:puerto/base?sslmode=require"
```

4. Reinicia la app.

Si `DATABASE_URL` no existe, la app usa automaticamente SQLite local en `data/reporting.db`.
