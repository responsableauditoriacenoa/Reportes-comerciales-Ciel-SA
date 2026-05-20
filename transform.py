from __future__ import annotations

from io import BytesIO
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from config import CANONICAL_COLUMNS, DEFAULT_KEY_COLUMNS


def read_excel(file) -> pd.DataFrame:
    return pd.read_excel(file, dtype=object)


def read_txt_table(file) -> pd.DataFrame:
    encodings = ["utf-8-sig", "latin1", "cp1252"]
    last_error = None
    for encoding in encodings:
        try:
            return pd.read_csv(file, sep=";", dtype=object, encoding=encoding, index_col=False)
        except UnicodeDecodeError as error:
            last_error = error
            if hasattr(file, "seek"):
                file.seek(0)
    raise last_error or ValueError("No se pudo leer el archivo TXT.")


def normalize_txt_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df.columns = [str(column).strip() for column in df.columns]

    for column in df.columns:
        if df[column].dtype == "object":
            df[column] = df[column].apply(lambda value: value.strip() if isinstance(value, str) else value)

    for column in [col for col in df.columns if "fecha" in col.lower()]:
        parsed = pd.to_datetime(df[column], format="%d/%m/%y", errors="coerce")
        missing = parsed.isna() & df[column].notna()
        if missing.any():
            parsed.loc[missing] = pd.to_datetime(df.loc[missing, column], dayfirst=True, errors="coerce")
        df[column] = parsed.dt.date.astype("string")

    if "Valor" in df.columns:
        df["Valor"] = df["Valor"].apply(_parse_amount)

    return df


def read_htm_margins(file) -> pd.DataFrame:
    content = _read_file_content(file)
    parser = _TableCellParser()
    parser.feed(content)

    rows = []
    for cells in parser.rows:
        clean_cells = [str(cell).strip() for cell in cells]
        if len(clean_cells) < 7:
            continue
        if "Concepto" in clean_cells and "Contrato" in clean_cells:
            continue

        concepto, cuota, fecha, suscripcion, contrato, creditos, debitos = clean_cells[:7]
        parsed_date = _parse_date_text(fecha)
        contract_digits = re.sub(r"\D", "", contrato)
        if len(contract_digits) < 7 or not concepto or parsed_date is None:
            continue

        grupo = contract_digits[:4]
        orden = contract_digits[4:7]
        importe = _parse_amount(creditos)
        if importe is None:
            debit = _parse_amount(debitos)
            importe = -debit if debit is not None else None

        rows.append(
            {
                "Contrato margen": contract_digits,
                "Grupo margen": grupo,
                "Orden margen": orden,
                "Concepto margen": concepto,
                "Importe margen": importe,
                "Fecha margen": parsed_date,
                "Suscripcion margen": suscripcion,
                "Cuota margen": cuota,
            }
        )

    return pd.DataFrame(rows)


def read_cuenta_h_txt(file) -> pd.DataFrame:
    content = _read_file_content(file)
    rows = []
    for line in content.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 12 or not re.match(r"^\d{8}$", parts[0]):
            continue
        if "**" in line or "Tot." in line:
            continue

        parsed = _parse_cuenta_h_parts(parts)
        if parsed is None or parsed.get("GL") != "H":
            continue
        rows.append(parsed)

    return pd.DataFrame(rows)


def _parse_cuenta_h_parts(parts: list[str]) -> dict | None:
    if len(parts) == 12:
        cuenta, gl, n_doc, tipo, texto, debito, credito, debito_usd, credito_usd, f_comp, f_valor, f_venc = parts
        n_factura = ""
    elif len(parts) >= 13:
        cuenta, gl, n_doc, tipo, texto, n_factura, debito, credito, debito_usd, credito_usd, f_comp, f_valor, f_venc = parts[:13]
    else:
        return None

    return {
        "Cuenta": cuenta,
        "GL": gl,
        "N.Doc.": n_doc,
        "Tipo": tipo,
        "Texto": texto,
        "Concepto": infer_cuenta_h_concept(texto),
        "N.Fac": n_factura,
        "Debito": _parse_amount(debito),
        "Credito": _parse_amount(credito),
        "Saldo": (_parse_amount(credito) or 0) - (_parse_amount(debito) or 0),
        "Debito U$": _parse_amount(debito_usd),
        "Credito U$": _parse_amount(credito_usd),
        "F.Comp.": _parse_compact_date(f_comp),
        "F.Valor": _parse_compact_date(f_valor),
        "F.Venc.": _parse_compact_date(f_venc),
    }


def infer_cuenta_h_concept(text: str) -> str:
    normalized = _normalize_text(text)
    if "FLETE" in normalized:
        return "Flete"
    if "FORMULARIO 01" in normalized:
        return "Formulario 01"
    if "BONIF" in normalized or "BONO" in normalized:
        return "Bonificaciones"
    if "PAGO SALDO" in normalized:
        return "Pago saldo"
    if "TRANSFERENCIA SALDOS" in normalized:
        return "Transferencia saldos"
    if "COMP PP" in normalized or "COMPENSACION" in normalized:
        return "Compensaciones"
    if "LICENCIAS SALESFORCE" in normalized:
        return "Licencias Salesforce"
    if "DESCUENTO" in normalized:
        return "Descuentos"
    if "RECUPERO" in normalized:
        return "Recuperos"
    return text.strip() if text else "Otros"


def default_txt_key_columns(df: pd.DataFrame) -> list[str]:
    for column in ["Pedido ABCnet", "Nro.Orden Produccion", "VIN", "Nro.Orden"]:
        if column in df.columns and df[column].notna().any():
            return [column]
    return [column for column in df.columns if df[column].notna().any()][:2]


def read_subscription_file(file) -> pd.DataFrame:
    name = getattr(file, "name", "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(file, dtype=object)
    return read_txt_table(file)


def read_public_google_sheet(sheet_id: str, gid: str | int = 0) -> pd.DataFrame:
    query = urlencode({"format": "csv", "gid": str(gid)})
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?{query}"
    with urlopen(url, timeout=30) as response:
        content = response.read()
    df = pd.read_csv(BytesIO(content), dtype=object)
    df.insert(0, "__sheet_row", range(2, len(df) + 2))
    return df


def normalize_subscriptions_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df.columns = [str(column).strip() for column in df.columns]
    rename_map = {}
    normalized_lookup = {_normalize_column_name(column): column for column in df.columns}

    aliases = {
        "fecha_ingreso": ["fecha_ingreso", "fecha ingreso", "f_ingreso", "f. de ingreso", "ingreso", "fecha"],
        "fecha_confirmacion_cliente": [
            "fecha_confirmacion_cliente",
            "fecha confirmacion cliente",
            "fecha confirmación cliente",
        ],
        "marca": ["marca", "brand", "peugeot", "citroen", "citroën"],
        "vendedor": ["vendedor", "asesor", "comercial", "salesperson"],
    }
    for target, candidates in aliases.items():
        for candidate in candidates:
            source = normalized_lookup.get(_normalize_column_name(candidate))
            if source:
                rename_map[source] = target
                break

    df = df.rename(columns=rename_map)
    for column in ["fecha_ingreso", "marca", "vendedor"]:
        if column not in df.columns:
            df[column] = None

    df["fecha_ingreso"] = df.apply(_parse_subscription_entry_date, axis=1).astype("string")
    df["marca"] = df["marca"].map(_normalize_subscription_brand).astype("string")
    df["vendedor"] = df["vendedor"].astype("string").str.strip().str.title()
    return df


def default_subscription_key_columns(df: pd.DataFrame) -> list[str]:
    preferred_groups = [
        ["__sheet_row"],
        ["solicitud"],
        ["solicitud_1"],
        ["id"],
        ["id_suscripcion"],
        ["suscripcion"],
        ["nro_suscripcion"],
        ["numero_suscripcion"],
        ["contrato"],
        ["dni"],
        ["documento"],
        ["cuit"],
        ["cuil"],
        ["cliente", "fecha_ingreso", "marca"],
        ["vendedor", "fecha_ingreso", "marca", "cliente"],
    ]
    normalized_lookup = {_normalize_column_name(column): column for column in df.columns}
    for group in preferred_groups:
        columns = [
            normalized_lookup[_normalize_column_name(column)]
            for column in group
            if _normalize_column_name(column) in normalized_lookup
        ]
        if len(columns) == len(group) and all(df[column].notna().any() for column in columns):
            return columns

    preferred = ["fecha_ingreso", "marca", "vendedor"]
    candidates = [column for column in preferred if column in df.columns and df[column].notna().any()]
    if candidates:
        extra_candidates = [column for column in df.columns if column not in candidates and df[column].notna().any()]
        return (candidates + extra_candidates)[:5]
    return [column for column in df.columns if df[column].notna().any()][:3]


def _parse_subscription_entry_date(row: pd.Series) -> str | None:
    value = row.get("fecha_ingreso")
    parsed = _parse_any_subscription_date(value)
    if pd.notna(parsed):
        current_year = int(pd.Timestamp.today().year)
        parsed_year_ok = 2024 <= int(parsed.year) <= current_year + 1
        if not parsed_year_ok:
            return None
        return parsed.date().isoformat()

    text = "" if _is_empty(value) else str(value).strip().lower()
    month_lookup = {
        "ene": 1,
        "enero": 1,
        "feb": 2,
        "febrero": 2,
        "mar": 3,
        "marzo": 3,
        "abr": 4,
        "abril": 4,
        "may": 5,
        "mayo": 5,
        "jun": 6,
        "junio": 6,
        "jul": 7,
        "julio": 7,
        "ago": 8,
        "agosto": 8,
        "sep": 9,
        "sept": 9,
        "septiembre": 9,
        "oct": 10,
        "octubre": 10,
        "nov": 11,
        "noviembre": 11,
        "dic": 12,
        "diciembre": 12,
    }
    match = re.search(r"(\d{1,2})\s*[-/]\s*([a-záéíóúñ]+)", text)
    if match:
        day = int(match.group(1))
        month = month_lookup.get(_normalize_column_name(match.group(2)).replace("_", ""))
        if month:
            year = int(pd.Timestamp.today().year)
            try:
                return pd.Timestamp(year=year, month=month, day=day).date().isoformat()
            except ValueError:
                pass

    return None


def _parse_any_subscription_date(value):
    if _is_empty(value):
        return pd.NaT

    text = str(value).strip()
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.notna(parsed):
        return parsed

    cleaned = re.sub(r"(?<=/)(\d{5})(?=$)", lambda match: match.group(1)[-4:], text)
    cleaned = re.sub(r"(?<=-)(\d{5})(?=$)", lambda match: match.group(1)[-4:], cleaned)
    if cleaned != text:
        parsed = pd.to_datetime(cleaned, dayfirst=True, errors="coerce")
        if pd.notna(parsed):
            return parsed

    compact = re.sub(r"[^\d/.-]", "", text)
    if compact and compact != text:
        parsed = pd.to_datetime(compact, dayfirst=True, errors="coerce")
        if pd.notna(parsed):
            return parsed

    return pd.NaT


def _normalize_subscription_brand(value) -> str:
    text = _clean_text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    if "CITROEN" in text:
        return "Citroen"
    if "PEUGEOT" in text:
        return "Peugeot"
    return str(value).strip().title() if not _is_empty(value) else ""


class _TableCellParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._current_row = []
        elif tag == "td" and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "td" and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(" ".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None


def _read_file_content(file) -> str:
    if hasattr(file, "read"):
        raw = file.read()
        if hasattr(file, "seek"):
            file.seek(0)
    else:
        with open(file, "rb") as handle:
            raw = handle.read()

    if isinstance(raw, str):
        return raw

    for encoding in ["cp1252", "latin1", "utf-8-sig"]:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="ignore")


def _parse_date_text(value) -> str | None:
    if _is_empty(value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return str(parsed.date())


def _parse_compact_date(value) -> str | None:
    text = str(value or "").strip()
    if not re.match(r"^\d{6}$", text):
        return None
    parsed = pd.to_datetime(text, format="%y%m%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return str(parsed.date())


def _normalize_text(value) -> str:
    value = str(value or "").strip().upper()
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char))


def normalize_dataframe(df: pd.DataFrame, column_mapping: dict[str, str] | None = None) -> pd.DataFrame:
    df = df.dropna(how="all").copy()
    df.columns = [_normalize_column_name(column) for column in df.columns]

    mapping = column_mapping or infer_column_mapping(df.columns)
    rename_map = {source: target for target, source in mapping.items() if source and source in df.columns}
    df = df.rename(columns=rename_map)

    for column in CANONICAL_COLUMNS:
        if column not in df.columns:
            df[column] = None

    df = add_derived_columns(df)
    df["fecha_matriculacion"] = pd.to_datetime(df["fecha_matriculacion"], errors="coerce").dt.date.astype("string")
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date.astype("string")
    df["fecha"] = df["fecha_matriculacion"].where(df["fecha_matriculacion"].notna(), df["fecha"])
    df["importe"] = df["importe"].apply(_parse_amount)
    df["matricula"] = df["matricula"].astype("string").str.strip().str.upper()
    df["factura"] = df["factura"].astype("string").str.strip()
    df = df[~df[["marca", "tipo_operacion", "fecha", "factura", "matricula", "importe", "cliente", "producto"]].apply(
        lambda row: all(_is_empty(value) for value in row),
        axis=1,
    )]
    df = df[~df.apply(_is_total_row, axis=1)]

    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "marca" not in df.columns:
        df["marca"] = None
    if "tipo_operacion" not in df.columns:
        df["tipo_operacion"] = None
    if "fecha_matriculacion" not in df.columns:
        df["fecha_matriculacion"] = None

    df["marca"] = df.apply(_infer_brand, axis=1)
    df["tipo_operacion"] = df.apply(_infer_sale_type_from_row, axis=1)
    df["fecha_matriculacion"] = df.apply(_infer_registration_date, axis=1)
    return df


def infer_column_mapping(columns) -> dict[str, str]:
    normalized_columns = list(columns)
    mapping = {}
    for target, aliases in CANONICAL_COLUMNS.items():
        normalized_aliases = {_normalize_column_name(alias) for alias in aliases}
        mapping[target] = next(
            (column for column in normalized_columns if column in normalized_aliases),
            "",
        )
    return mapping


def available_key_columns(df: pd.DataFrame) -> list[str]:
    candidates = [column for column in DEFAULT_KEY_COLUMNS if column in df.columns and df[column].notna().any()]
    if candidates:
        return candidates
    return [column for column in df.columns if df[column].notna().any()][:3]


def _normalize_column_name(value) -> str:
    value = str(value).strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def _parse_amount(value):
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _infer_brand(row: pd.Series) -> str:
    marca = _clean_text(row.get("marca"))
    producto = _clean_text(row.get("producto"))
    codigo = _clean_text(row.get("cod_modelo"))
    bastidor = _clean_text(row.get("bastidor"))

    if marca in {"1", "1.0"}:
        return "Peugeot"
    if marca in {"2", "2.0"}:
        return "Citroen"

    joined = " ".join([marca, producto, codigo, bastidor])
    if any(token in joined for token in ["PEUGEOT", " 208", "2008", "1PP", "8AD"]):
        return "Peugeot"
    if any(token in joined for token in ["CITROEN", "C3", "AIRCROSS", "BASALT", "1CS", "935"]):
        return "Citroen"

    return marca.title() if marca else ""


def _infer_sale_type(value) -> str:
    text = _clean_text(value)
    if text in {"PLAN DE AHORRO", "PLAN AHORRO", "AHORRO"}:
        return "Plan de ahorro"
    if text in {"VENTA CONVENCIONAL", "CONVENCIONAL"}:
        return "Venta convencional"
    if text in {"5", "5.0"}:
        return "Plan de ahorro"
    if text:
        return "Venta convencional"
    return ""


def _infer_sale_type_from_row(row: pd.Series) -> str:
    sale_type = _infer_sale_type(row.get("tipo_operacion"))
    if sale_type:
        return sale_type
    return _infer_sale_type(row.get("t_venta"))


def _infer_registration_date(row: pd.Series):
    for column in ["fecha_matriculacion", "f_matric", "f_matricula", "fecha"]:
        value = row.get(column)
        if not _is_empty(value):
            return value
    return None


def _clean_text(value) -> str:
    if _is_empty(value):
        return ""
    return str(value).strip().upper()


def _is_total_row(row: pd.Series) -> bool:
    joined = " ".join(_clean_text(value) for value in row.values)
    return "*** TOT" in joined or joined.startswith("TOTAL ")


def _is_empty(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value).strip() == ""
