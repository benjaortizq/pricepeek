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

## Prerrequisitos del reporte PDF

El reporte usa `weasyprint==70.0`. Además del paquete de Python, WeasyPrint
necesita las bibliotecas de sistema Pango, Cairo y sus dependencias. La guía
oficial de instalación está en
<https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>. En Debian o
Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y \
  libpango-1.0-0 \
  libpangoft2-1.0-0 \
  libharfbuzz0b \
  libharfbuzz-subset0 \
  libcairo2 \
  libgdk-pixbuf-2.0-0 \
  libffi8 \
  shared-mime-info \
  fonts-dejavu-core
```

WeasyPrint 70 requiere Pango 1.44 o posterior. Compruebe la versión y la
importación de la biblioteca antes de desplegar:

```bash
pango-view --version
python -c "from weasyprint import HTML; print('WeasyPrint OK')"
```

En Windows, la opción más sencilla es usar WSL2, un contenedor Linux o una
imagen de servidor con Pango y Cairo. También puede instalar Pango con MSYS2
(UCRT64) y apuntar WeasyPrint a sus DLL:

```powershell
pacman -S mingw-w64-ucrt-x86_64-pango
$env:WEASYPRINT_DLL_DIRECTORIES = "C:\msys64\ucrt64\bin"
python -m weasyprint --info
```

La instalación de WeasyPrint en Python por sí sola no incluye las bibliotecas
nativas de Pango y Cairo.

Si faltan las bibliotecas, el resto del portal sigue funcionando y la acción
de descargar el PDF muestra un aviso en lugar de romper la aplicación.

## Pruebas

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test enterprise.tests
```

Las pruebas de `enterprise` crean manualmente las tablas no administradas de
Supabase (`Stores`, `Products`, `ProductVariants`, `Prices`, etc.) porque el
modelo Django las declara con `managed = False`.
