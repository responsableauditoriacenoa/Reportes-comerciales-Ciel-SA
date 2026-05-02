from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reporting.db"


CANONICAL_COLUMNS = {
    "marca": [
        "marca",
        "brand",
        "concesi",
        "concesionario",
    ],
    "tipo_operacion": [
        "tipo_operacion",
        "tipo operacion",
        "tipo operación",
        "tipo venta",
        "t.venta",
        "t venta",
        "t_venta",
    ],
    "fecha_matriculacion": [
        "fecha_matriculacion",
        "fecha matriculacion",
        "fecha matriculación",
        "f.matric",
        "f matric",
        "f_matric",
    ],
    "fecha": [
        "fecha",
        "fecha factura",
        "fecha_factura",
        "fecha de factura",
        "fecha venta",
        "fecha_venta",
        "fec.fact",
        "fec fact",
        "fec_fact",
        "f.cierre",
        "f cierre",
        "f_cierre",
        "periodo",
    ],
    "factura": [
        "factura",
        "nro factura",
        "numero factura",
        "número factura",
        "nro_factura",
        "comprobante",
        "nro comprobante",
        "refer.",
        "refer",
        "referencia",
        "cta.factur",
        "cta factur",
        "cta_factur",
    ],
    "matricula": [
        "matricula",
        "matrícula",
        "patente",
        "dominio",
        "chasis",
        "vin",
    ],
    "importe": [
        "importe",
        "facturacion",
        "facturación",
        "monto",
        "total",
        "total factura",
        "t.factura",
        "t factura",
        "t_factura",
        "neto",
    ],
    "cliente": [
        "cliente",
        "razon social",
        "razón social",
        "comprador",
        "titular",
        "nombre cliente",
        "nombre_cliente",
    ],
    "producto": [
        "producto",
        "modelo",
        "unidad",
        "vehiculo",
        "vehículo",
        "version",
        "versión",
        "modelo v.n.",
        "modelo v n",
        "modelo_v_n",
    ],
}


DEFAULT_KEY_COLUMNS = ["factura", "matricula"]
