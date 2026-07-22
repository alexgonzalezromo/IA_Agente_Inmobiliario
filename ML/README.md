# Estimación del precio de viviendas

`predict_houses_value.py` entrena un modelo con los anuncios residenciales de
`data/properties.db` y actualiza la tabla `properties`.

## Ejecución

Desde la raíz del proyecto:

```powershell
python ML/predict_houses_value.py
```

Eso ejecuta el pipeline de entrenamiento completo. Después de un scraping,
puede reutilizarse el modelo sin reentrenar:

```powershell
python ML/predict_houses_value.py --mode predict
```

Conviene volver a ejecutar `--mode train` periódicamente (por ejemplo, tras
añadir un bloque relevante de anuncios) para que el modelo aprenda los datos
nuevos. `--mode predict` es la ruta rápida para actualizar estimaciones entre
entrenamientos.

## Integración con los scrapers

El flujo habitual es:

```powershell
python scrapers/run_all_scrapers.py
```

Después de ejecutar las fuentes, el orquestador:

1. Reentrena si hay 50 viviendas válidas más que en el último entrenamiento o
   si el modelo tiene 7 días.
2. En caso contrario, reutiliza el modelo existente para actualizar todas las
   estimaciones.

Los umbrales pueden cambiarse:

```powershell
python scrapers/run_all_scrapers.py --retrain-threshold 100 --retrain-days 14
```

Comandos operativos útiles:

```powershell
# Ejecutar solo algunas fuentes
python scrapers/run_all_scrapers.py --sources fotocasa idealista

# Limitar páginas por fuente durante una prueba
python scrapers/run_all_scrapers.py --max-pages 2

# Comprobar/actualizar únicamente ML, sin acceso a las webs
python scrapers/run_all_scrapers.py --ml-only

# Hacer scraping sin ejecutar ML
python scrapers/run_all_scrapers.py --skip-ml
```

El script crea o actualiza estas columnas:

- `estimated_price`: valor de mercado estimado en euros.
- `price_difference`: `price - estimated_price`; positivo significa que el
  anuncio pide más que la estimación.
- `price_vs_estimate`: `above`, `below` o `near` (margen del 5 % por defecto).
- `estimated_at`: momento UTC en el que se calculó la estimación.

Las estimaciones escritas para los anuncios existentes son predicciones fuera
de muestra mediante validación cruzada. El artefacto
`ML/house_price_model.joblib` queda entrenado con todos los datos disponibles.

Para cambiar el margen de `near`:

```powershell
python ML/predict_houses_value.py --near-threshold 0.10
```

## Limitaciones

El objetivo de entrenamiento es el precio anunciado, no el precio final de
compraventa. Con pocos anuncios, la estimación sirve como indicador de
comparables y no como tasación profesional. Debe reentrenarse después de
incorporar nuevos anuncios.
