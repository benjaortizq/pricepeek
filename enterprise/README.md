# Portal de empresas

Portal Django para que una cuenta `enterprise` administre exclusivamente los
precios de la tienda asignada en `accounts_user.from_store`.

## Puesta en marcha

1. Instale las dependencias de Python:

   ```bash
   python -m pip install -r requirements.txt
   ```

2. Aplique las migraciones:

   ```bash
   python manage.py migrate
   ```

3. Inicie el servidor de desarrollo:

   ```bash
   python manage.py runserver
   ```

El portal queda disponible en `/enterprise/panel/`. La cuenta debe tener rol
`enterprise` y una tienda asignada; la tienda nunca se toma de un parámetro
enviado por el navegador.

## Importación CSV

La plantilla se descarga desde `/enterprise/catalogo/plantilla.csv/`. Sus
columnas canónicas son:

```text
gtin,product_name,variant_name,brand_id,category_id,attributes,price,discount,is_available,product_web_url
```

- `gtin` y `price` son obligatorios.
- `discount` es un decimal entre `0` y `1`; vacío significa `0`.
- `attributes` debe contener un objeto JSON.
- Para un GTIN nuevo se requieren `product_name`, `variant_name`, `brand_id` y
  `category_id`; la marca y la categoría deben existir.
- La tienda, la moneda y las fechas se asignan en el servidor. No se importa
  `id_store`.
- Cada fila se procesa de forma independiente. Las filas inválidas se reportan
  sin impedir la importación de las demás.

Un GTIN existente agrega únicamente el precio de la tienda. Un GTIN nuevo crea
un producto mínimo, una variante y el precio correspondiente.

## Reporte PDF

El reporte de competitividad se genera con `reportlab==4.5.1` mediante
Platypus. ReportLab se instala con `pip` y no necesita bibliotecas de sistema
adicionales, por lo que el mismo procedimiento funciona en Windows, macOS y
Linux. Las fuentes Bitstream Vera incluidas en ReportLab se usan para mostrar
correctamente tildes y la `ñ`.

Después de instalar `requirements.txt`, la acción **Reporte PDF** del portal
descarga directamente el documento. El archivo incluye el nombre de la tienda,
la fecha de generación, el resumen de competitividad, los productos por encima
del mercado y los precios desactualizados según `STALE_PRICE_DAYS`.

Para comprobar la generación de forma automatizada:

```bash
python manage.py test enterprise.tests
```

Las pruebas generan un PDF real y verifican su estructura, el idioma y los
datos incluidos. Para una comprobación manual, inicie el servidor, ingrese con
una cuenta `enterprise` que tenga tienda asignada y descargue el reporte desde
el tablero.

## Pruebas

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test enterprise.tests
```

Las pruebas de `enterprise` crean manualmente las tablas no administradas de
Supabase (`Stores`, `Products`, `ProductVariants`, `Prices`, etc.) porque el
modelo Django las declara con `managed = False`.
