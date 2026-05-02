# Reporting de Patentamientos

Aplicacion Streamlit para importar archivos Excel de ventas, consolidar datos historicos en SQLite y visualizar KPIs de patentamientos y facturacion.

## Funcionalidades

- Importacion de archivos `.xlsx`, `.xls` y reportes exportados desde el sistema de gestion.
- Importacion de archivos `.txt` separados por punto y coma, con base historica persistente.
- Mapeo flexible de columnas para adaptar distintos formatos de Excel.
- Persistencia local en `data/reporting.db`.
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

La base `data/reporting.db` queda fuera de Git por seguridad y para evitar subir datos sensibles. Si queres compartir datos entre equipos, conviene usar una base externa o un archivo SQLite controlado por backup privado.
