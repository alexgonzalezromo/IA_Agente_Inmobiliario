# AI Agente Inmobiliario

Proyecto personal para buscar, comparar y visualizar viviendas en Campoamor de
una forma más cómoda que ir portal por portal.

La idea es sencilla: recoger anuncios de distintas webs inmobiliarias, guardar
los datos importantes, estimar si el precio parece razonable con machine
learning y generar un portal propio para revisar las oportunidades con calma.

## Ver el portal

[Ver portal inmobiliario](https://alexgonzalezromo.github.io/IA_Agente_Inmobiliario/portal/)

El portal muestra las viviendas con fotos, filtros, ordenación, fichas
individuales, galería de imágenes y enlace directo al anuncio original.

## Qué hace

- Recopila viviendas de varias fuentes inmobiliarias.
- Se centra en Campoamor y alrededores.
- Guarda precio, metros, habitaciones, baños, ubicación, fotos y enlace original.
- Evita mostrar anuncios repetidos en el portal.
- Calcula métricas útiles como precio por metro cuadrado.
- Usa un modelo de machine learning para estimar el precio esperado.
- Compara el precio publicado con esa estimación.
- Genera una web estática para revisar los anuncios de forma visual.

## Por qué lo hice

Buscar vivienda puede volverse bastante caótico: muchas pestañas abiertas,
anuncios repetidos, precios difíciles de comparar y oportunidades que se pierden
entre varias webs.

Este proyecto intenta ordenar todo eso en un solo sitio. No busca reemplazar una
tasación profesional, pero sí ayudar a filtrar mejor y detectar anuncios que
merecen una segunda mirada.

## Fuentes

Ahora mismo el agente trabaja con anuncios de:

- Fotocasa
- Idealista
- Milanuncios
- Moreno Schmidt
- United Real Estate

Cada web tiene su propia estructura y sus propios límites, así que una parte
importante del proyecto es mantener los scrapers y añadir nuevas fuentes poco a
poco.

## Machine learning

El modelo estima el precio usando variables como metros, habitaciones, baños,
zona, tipo de vivienda, distancia a la playa y detalles encontrados en el texto
del anuncio.

La estimación sirve como referencia rápida para distinguir anuncios caros,
ajustados o potencialmente interesantes.

## Próximos pasos

- Mejorar el scoring de oportunidades.
- Añadir más fuentes inmobiliarias.
- Automatizar la ejecución en un servidor.
- Hacer que el portal se actualice solo con nuevos anuncios.
