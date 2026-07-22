# AI Agente Inmobiliario

Este proyecto nace de una idea muy simple: estaba mirando casas por Campoamor y
me di cuenta de que buscar bien una vivienda es mucho más pesado de lo que
parece.

Tienes que entrar en varias webs, repetir búsquedas, abrir anuncios que a veces
ya habías visto, comparar precios a ojo, guardar enlaces, mirar fotos, revisar
si realmente está cerca de la zona que quieres... y al final es fácil perderse
o dejar pasar algo interesante.

Así que pensé: ¿y si hago un agente que me ayude con todo eso?

La idea es que el programa busque anuncios por mí, junte la información
importante, compare precios con un modelo de machine learning y me genere un
portal propio para ver las viviendas de una forma mucho más clara.

## Ver el portal

Cuando GitHub Pages esté activado, el portal se podrá ver aquí:

[Ver portal inmobiliario](https://alexgonzalezromo.github.io/IA_Agente_Inmobiliario/portal/)

Ahí se ven los anuncios con fotos, filtros, ordenación, fichas individuales,
galería de imágenes y un botón para ir directamente al anuncio original.

## Qué hace

El agente recopila viviendas de distintas webs inmobiliarias y se queda con los
datos que de verdad me interesan: precio, metros, habitaciones, baños, ubicación,
fotos, enlace original y algunos detalles del anuncio.

Después usa un modelo de machine learning para estimar si el precio parece estar
por encima, cerca o por debajo de lo esperable. No lo planteo como una tasación
profesional, sino como una ayuda rápida para ordenar mejor los anuncios y
detectar oportunidades que merecen una segunda mirada.

Lo que más me gusta es que no se queda en un script que imprime cosas por
pantalla. El resultado acaba siendo una web estática, visual y fácil de revisar,
casi como un mini portal inmobiliario hecho a mi medida.

## Por qué me hacía ilusión hacerlo

Porque junta varias cosas que me gustan mucho: automatización, scraping, datos,
machine learning y una interfaz que realmente se puede usar.

También me gusta porque no es un proyecto inventado sin contexto. Sale de una
necesidad bastante real: querer buscar mejor, ahorrar tiempo y tener una forma
más inteligente de comparar viviendas.

## Fuentes

Ahora mismo estoy trabajando con anuncios de Fotocasa, Idealista, Milanuncios,
Moreno Schmidt y United Real Estate.

Cada web funciona de una manera distinta y algunas cambian bastante, así que una
parte importante del proyecto es ir haciendo los scrapers más sólidos y añadir
nuevas fuentes poco a poco.

## Lo siguiente

Me gustaría seguir mejorando el scoring, añadir más fuentes, cuidar todavía más
la parte visual del portal y acabar desplegándolo para que se actualice solo
desde un servidor.

La idea final sería tener un agente funcionando en segundo plano, buscando
viviendas nuevas y dejando el portal listo para abrirlo y revisar las mejores
opciones sin tener que empezar desde cero cada vez.
