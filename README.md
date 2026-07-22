# AI Agente Inmobiliario

Este proyecto nace de una idea bastante sencilla: si quiero encontrar buenas
casas en Campoamor, prefiero que un programa haga la parte repetitiva por mi.

La idea es juntar anuncios de varias webs, guardar los datos en una base SQLite,
estimar si el precio parece razonable con un modelo de machine learning y generar
un portal estatico bonito para revisar las viviendas con calma, con sus fotos,
filtros y enlace directo al anuncio original.

No pretende ser una tasacion profesional ni sustituir mirar una casa de verdad.
Es mas bien una herramienta para no perder oportunidades y comparar anuncios con
un poco mas de criterio.

## Portal de ejemplo

El proyecto genera un portal HTML en:

[Abrir portal de ejemplo](portal/index.html)

Si lo estas viendo desde GitHub, puede que el enlace abra el HTML como codigo.
Para verlo como pagina, descarga el repo y abre `portal/index.html` en el
navegador. Mas adelante se puede publicar igual con GitHub Pages o en un VPS.

## Que hace ahora mismo

- Busca viviendas en Campoamor/Orihuela Costa en varias fuentes.
- Guarda los anuncios en `data/properties.db`.
- Detecta anuncios nuevos y cambios de precio.
- Calcula precio por metro cuadrado y otros datos utiles.
- Entrena un modelo con scikit-learn para estimar el precio anunciado.
- Compara precio real vs estimado y marca si esta por encima, cerca o por debajo.
- Genera un portal estatico con fotos, filtros, ordenacion y fichas individuales.
- En cada ficha se pueden pasar las fotos y abrir el anuncio original.

## Fuentes incluidas

Ahora mismo hay scrapers para:

- Fotocasa
- Idealista
- Milanuncios
- Moreno Schmidt
- United Real Estate

Algunas webs cambian mucho, bloquean peticiones o cargan contenido de forma
dinamica. Por eso los scrapers intentan ser prudentes y, cuando tiene sentido,
usar cache local durante pruebas.

## Modelo de machine learning

El modelo esta en `ML/predict_houses_value.py`.

Usa un `Pipeline` de scikit-learn con:

- imputacion de valores numericos
- one-hot encoding para variables categoricas
- `RandomForestRegressor`

Las variables principales son metros, habitaciones, banos, distancia a la playa,
fuente, zona, tipo de vivienda y algunas pistas sacadas del texto, como piscina,
terraza, garaje o vistas al mar.

## Instalacion

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

Ejecutar todo el flujo:

```powershell
python main.py
```

Probar con pocas paginas:

```powershell
python main.py --max-pages 1
```

Solo actualizar el modelo sin volver a scrapear:

```powershell
python main.py --ml-only
```

Generar el portal:

```powershell
python app\portal_generator.py
```

El resultado queda en `portal/index.html`.

## Estructura

```text
app/        base de datos y generador del portal
ML/         modelo de estimacion de precios con scikit-learn
scrapers/   scrapers de las distintas fuentes
portal/     ejemplo generado del portal HTML
data/       base de datos local, ignorada en Git
```

## Cosas que quiero mejorar

- Anadir mas fuentes inmobiliarias que tengan viviendas en Campoamor.
- Afinar el scoring para que no sea solo precio, tambien calidad del anuncio.
- Publicar el portal para poder verlo sin abrir archivos locales.
- Separar mejor backend y frontend si el proyecto crece.
- Preparar una ejecucion periodica en un VPS.

## Nota

Este proyecto es para aprendizaje y uso personal. Las webs pueden cambiar sus
condiciones o su estructura, asi que los scrapers pueden necesitar ajustes con el
tiempo.
