# AI Agente Inmobiliario

Este proyecto es mi intento de convertir una busqueda inmobiliaria normal en
algo mucho mas comodo, visual y con datos.

La idea empezo con una pregunta bastante simple: si estoy mirando casas en
Campoamor, por que tengo que ir web por web, abrir anuncios repetidos, comparar
precios a ojo y perder viviendas interesantes entre tantas pestanas?

Asi que empece a construir un agente que busca anuncios, guarda la informacion
importante, estima si el precio tiene sentido y genera un portal propio para
revisarlo todo con calma.

## Ver el portal

Cuando GitHub Pages este activado, el portal se podra ver aqui:

[Ver portal inmobiliario](https://alexgonzalezromo.github.io/IA_Agente_Inmobiliario/portal/)

El portal incluye anuncios con foto, filtros, ordenacion, fichas individuales,
galeria de imagenes y enlace directo a la web original de cada vivienda.

## Que hace

- Reune anuncios de varias webs inmobiliarias.
- Se centra en viviendas de Campoamor y alrededores.
- Guarda precio, metros, habitaciones, banos, ubicacion, fotos y enlace original.
- Calcula datos utiles como precio por metro cuadrado.
- Usa machine learning para estimar el valor aproximado de cada vivienda.
- Compara el precio anunciado con esa estimacion.
- Genera una web estatica para ver las mejores oportunidades de forma clara.

## Por que me gusta este proyecto

Porque mezcla varias cosas que me interesan mucho: automatizacion, datos,
machine learning y una interfaz que realmente sirve para tomar decisiones.

No queria hacer solo un script que escupe resultados por consola. Queria llegar
a algo que se pudiera abrir, mirar y entender rapido, casi como si fuera mi
propio mini portal inmobiliario.

## Fuentes que estoy trabajando

Ahora mismo el proyecto trabaja con varias fuentes, entre ellas Fotocasa,
Idealista, Milanuncios, Moreno Schmidt y United Real Estate.

Cada web es un mundo y algunas cambian bastante o ponen limites, asi que parte
del proyecto tambien consiste en ir haciendo los scrapers mas resistentes y
anadir nuevas fuentes poco a poco.

## Machine learning

La parte de ML intenta estimar el precio de una vivienda usando datos como
metros, habitaciones, banos, zona, tipo de vivienda, distancia a la playa y
extras que aparecen en el texto del anuncio.

No es una tasacion profesional, pero si sirve como una referencia rapida para
detectar anuncios que parecen caros, ajustados o potencialmente interesantes.

## Siguientes pasos

Quiero seguir mejorandolo con mas fuentes, mejores fotos, scoring mas fino y una
version desplegada para que el portal se pueda consultar siempre online.

La idea final es que el agente pueda ejecutarse en un servidor, actualizar los
anuncios automaticamente y dejar el portal listo sin tener que hacerlo a mano.
