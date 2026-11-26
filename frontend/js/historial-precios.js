/* Gráfico del historial de precios (issue «Historial de precios»).
 *
 * Dibuja en SVG, al ancho de su tarjeta, los datos que deja
 * products/templates/products/historial_precios.html con json_script
 * (products/historial.py, graficos_del_producto). Una línea escalonada por
 * tienda: el precio se mantiene hasta que cambia, y si la tienda no tenía el
 * producto disponible la línea se corta.
 *
 * Al pasar el puntero (o con las flechas del teclado) una línea vertical
 * marca la fecha y un cuadro muestra el precio de cada tienda ese día. Los
 * mismos datos están en la tabla de abajo del gráfico, así no hace falta el
 * puntero para leerlos.
 */
(() => {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";
  const ZONA = "America/Costa_Rica";
  const ALTO = 220; // alto del área de las líneas
  const ARRIBA = 12;
  const ABAJO = 28; // espacio de los meses
  const DERECHA = 12;

  const miles = (valor) =>
    String(Math.round(valor)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");

  const idioma = () =>
    (document.documentElement.lang || "es").toLowerCase().startsWith("en")
      ? "en-US"
      : "es-CR";

  function nodo(nombre, atributos, padre) {
    const elemento = document.createElementNS(SVG, nombre);
    Object.entries(atributos || {}).forEach(([clave, valor]) =>
      elemento.setAttribute(clave, valor)
    );
    if (padre) padre.appendChild(elemento);
    return elemento;
  }

  /* Valores redondos para el eje del precio (₡1.000, ₡1.250, …). */
  function marcasDelPrecio(minimo, maximo) {
    if (minimo === maximo) {
      const margen = Math.max(10, minimo * 0.1);
      minimo -= margen;
      maximo += margen;
    }
    const bruto = (maximo - minimo) / 4;
    const potencia = 10 ** Math.floor(Math.log10(bruto));
    // Los colones no tienen decimales: el paso más chico es ₡1.
    const paso = Math.max(
      1,
      [1, 2, 2.5, 5, 10]
        .map((factor) => factor * potencia)
        .find((candidato) => candidato >= bruto)
    );
    const inicio = Math.max(0, Math.floor(minimo / paso) * paso);
    const marcas = [];
    for (let valor = inicio; valor < maximo + paso; valor += paso) {
      marcas.push(Math.round(valor));
      if (valor >= maximo) break;
    }
    return marcas;
  }

  /* El precio de la tienda en ese momento: undefined si todavía no había
   * datos, null si no lo tenía disponible. */
  function valorEn(puntos, momento) {
    let valor;
    for (const [fecha, precio] of puntos) {
      if (fecha > momento) break;
      valor = precio;
    }
    return valor;
  }

  /* El trazo escalonado de una tienda, cortado donde no había precio. */
  function trazo(puntos, x, y) {
    let d = "";
    let anterior = null;
    for (const [fecha, valor] of puntos) {
      const habia = anterior !== null && anterior !== undefined;
      if (habia) d += ` H${x(fecha).toFixed(1)}`;
      if (valor !== null) {
        d += habia
          ? ` V${y(valor).toFixed(1)}`
          : ` M${x(fecha).toFixed(1)} ${y(valor).toFixed(1)}`;
      }
      anterior = valor;
    }
    return d.trim();
  }

  function iniciar(lienzo) {
    const fuente = document.getElementById(lienzo.dataset.historial);
    if (!fuente) return;
    const datos = JSON.parse(fuente.textContent);
    const textos = {
      noDisponible: lienzo.dataset.textoNoDisponible || "No disponible",
      sinDatos: lienzo.dataset.textoSinDatos || "Sin datos",
    };
    const formatoFecha = new Intl.DateTimeFormat(idioma(), {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: ZONA,
    });
    const momentos = [
      ...new Set(
        datos.series.flatMap((serie) => serie.puntos.map(([fecha]) => fecha))
      ),
    ].sort((a, b) => a - b);

    const tooltip = document.createElement("div");
    tooltip.className = "historial-tooltip";
    tooltip.hidden = true;
    const anuncio = document.createElement("p");
    anuncio.className = "sr-only";
    anuncio.setAttribute("aria-live", "polite");
    lienzo.append(tooltip, anuncio);

    let escala = null; // lo que mide el dibujo actual
    let actual = null; // el momento que marca la línea vertical

    function dibujar() {
      const ancho = lienzo.clientWidth;
      if (!ancho) return; // la pestaña de la presentación está escondida
      lienzo.querySelector("svg")?.remove();

      const valores = datos.series
        .flatMap((serie) => serie.puntos.map(([, valor]) => valor))
        .filter((valor) => valor !== null);
      const marcas = marcasDelPrecio(Math.min(...valores), Math.max(...valores));
      const yMin = marcas[0];
      const yMax = marcas[marcas.length - 1];
      const largo = Math.max(
        ...marcas.map((marca) => (datos.simbolo + miles(marca)).length)
      );
      const izquierda = 10 + largo * 7;
      const derecha = ancho - DERECHA;
      const alto = ARRIBA + ALTO + ABAJO;
      const x = (fecha) =>
        izquierda +
        ((fecha - datos.desde) / (datos.hasta - datos.desde)) *
          (derecha - izquierda);
      const y = (valor) =>
        ARRIBA + (1 - (valor - yMin) / (yMax - yMin)) * ALTO;

      const svg = nodo("svg", {
        class: "historial-svg",
        width: ancho,
        height: alto,
        viewBox: `0 0 ${ancho} ${alto}`,
        "aria-hidden": "true",
        focusable: "false",
      });

      const cuadricula = nodo("g", { class: "historial-cuadricula" }, svg);
      marcas.forEach((marca) => {
        if (marca !== yMin) {
          nodo(
            "line",
            { x1: izquierda, x2: derecha, y1: y(marca), y2: y(marca) },
            cuadricula
          );
        }
        const texto = nodo(
          "text",
          {
            class: "historial-eje-texto",
            x: izquierda - 8,
            y: y(marca),
            "text-anchor": "end",
            "dominant-baseline": "middle",
          },
          svg
        );
        texto.textContent = datos.simbolo + miles(marca);
      });

      const base = ARRIBA + ALTO;
      nodo(
        "line",
        { class: "historial-base", x1: izquierda, x2: derecha, y1: base, y2: base },
        svg
      );
      const espacio = (derecha - izquierda) / Math.max(1, datos.meses.length);
      const cada = espacio < 40 ? 2 : 1;
      datos.meses.forEach((mes, indice) => {
        const posicion = x(mes.t);
        nodo(
          "line",
          { class: "historial-base", x1: posicion, x2: posicion, y1: base, y2: base + 4 },
          svg
        );
        if (indice % cada || posicion + 24 > derecha) return;
        const texto = nodo(
          "text",
          { class: "historial-eje-texto", x: posicion + 4, y: base + 18 },
          svg
        );
        texto.textContent = mes.texto;
      });

      datos.series.forEach((serie) => {
        const clase = `serie-${serie.color}${serie.punteada ? " punteada" : ""}`;
        nodo("path", { class: `historial-linea ${clase}`, d: trazo(serie.puntos, x, y) }, svg);
        const [inicio, valorInicial] = serie.puntos[0];
        const [fin, valorFinal] = serie.puntos[serie.puntos.length - 1];
        // Dónde empieza el historial de la tienda, si empieza dentro del gráfico.
        if (valorInicial !== null && inicio > datos.desde && x(fin) - x(inicio) > 10) {
          nodo("circle", { class: `historial-punto ${clase}`, cx: x(inicio), cy: y(valorInicial), r: 4 }, svg);
        }
        if (valorFinal !== null) {
          nodo("circle", { class: `historial-punto ${clase}`, cx: x(fin), cy: y(valorFinal), r: 4 }, svg);
        }
      });

      const cruz = nodo(
        "line",
        { class: "historial-cruz", y1: ARRIBA, y2: base, visibility: "hidden" },
        svg
      );
      const puntos = datos.series.map((serie) =>
        nodo(
          "circle",
          { class: `historial-punto serie-${serie.color}`, r: 5, visibility: "hidden" },
          svg
        )
      );
      // El área que responde al puntero es todo el gráfico, no solo las líneas.
      const captura = nodo(
        "rect",
        {
          class: "historial-captura",
          x: izquierda,
          y: 0,
          width: Math.max(0, derecha - izquierda),
          height: alto,
        },
        svg
      );
      captura.addEventListener("pointermove", (evento) => {
        const caja = svg.getBoundingClientRect();
        const posicion = Math.min(
          derecha,
          Math.max(izquierda, evento.clientX - caja.left)
        );
        mostrar(
          datos.desde +
            ((posicion - izquierda) / (derecha - izquierda)) *
              (datos.hasta - datos.desde)
        );
      });
      captura.addEventListener("pointerleave", () => {
        if (document.activeElement !== lienzo) esconder();
      });

      lienzo.prepend(svg);
      escala = { x, y, cruz, puntos, izquierda, derecha };
      if (actual !== null) mostrar(actual);
    }

    function mostrar(momento, anunciar) {
      if (!escala) return;
      actual = momento;
      const posicion = escala.x(momento);
      escala.cruz.setAttribute("x1", posicion);
      escala.cruz.setAttribute("x2", posicion);
      escala.cruz.setAttribute("visibility", "visible");

      const fecha = formatoFecha.format(new Date(momento));
      const lista = document.createElement("ul");
      const partes = [];
      datos.series.forEach((serie, indice) => {
        const valor = valorEn(serie.puntos, momento);
        const punto = escala.puntos[indice];
        if (typeof valor === "number") {
          punto.setAttribute("cx", posicion);
          punto.setAttribute("cy", escala.y(valor));
          punto.setAttribute("visibility", "visible");
        } else {
          punto.setAttribute("visibility", "hidden");
        }
        const texto =
          typeof valor === "number"
            ? datos.simbolo + miles(valor)
            : valor === null
              ? textos.noDisponible
              : textos.sinDatos;
        const fila = document.createElement("li");
        const clave = document.createElement("span");
        clave.className = `historial-clave serie-${serie.color}${serie.punteada ? " punteada" : ""}`;
        const precio = document.createElement("strong");
        precio.textContent = texto;
        const tienda = document.createElement("span");
        tienda.className = "historial-tooltip-tienda";
        tienda.textContent = serie.tienda;
        fila.append(clave, precio, tienda);
        lista.appendChild(fila);
        partes.push(`${serie.tienda}: ${texto}`);
      });
      const titulo = document.createElement("p");
      titulo.className = "historial-tooltip-fecha";
      titulo.textContent = fecha;
      tooltip.replaceChildren(titulo, lista);
      tooltip.hidden = false;

      const ancho = tooltip.offsetWidth;
      const izquierda =
        posicion + 12 + ancho <= lienzo.clientWidth
          ? posicion + 12
          : Math.max(0, posicion - 12 - ancho);
      tooltip.style.transform = `translate(${izquierda}px, ${ARRIBA}px)`;
      if (anunciar) anuncio.textContent = `${fecha}. ${partes.join(". ")}.`;
    }

    function esconder() {
      actual = null;
      tooltip.hidden = true;
      if (!escala) return;
      escala.cruz.setAttribute("visibility", "hidden");
      escala.puntos.forEach((punto) => punto.setAttribute("visibility", "hidden"));
    }

    // Con el teclado: las flechas recorren las fechas en que cambió algún precio.
    lienzo.addEventListener("keydown", (evento) => {
      if (!momentos.length) return;
      const ahora = actual ?? datos.hasta;
      const primero = momentos[0];
      const ultimo = momentos[momentos.length - 1];
      let destino;
      if (evento.key === "ArrowRight") {
        destino = momentos.find((momento) => momento > ahora) ?? ultimo;
      } else if (evento.key === "ArrowLeft") {
        destino = [...momentos].reverse().find((momento) => momento < ahora) ?? primero;
      } else if (evento.key === "Home") {
        destino = primero;
      } else if (evento.key === "End") {
        destino = ultimo;
      } else if (evento.key === "Escape") {
        esconder();
        return;
      } else {
        return;
      }
      evento.preventDefault();
      mostrar(destino, true);
    });
    lienzo.addEventListener("focus", () => mostrar(actual ?? datos.hasta, true));
    lienzo.addEventListener("blur", esconder);

    let pendiente = false;
    new ResizeObserver(() => {
      if (pendiente) return;
      pendiente = true;
      requestAnimationFrame(() => {
        pendiente = false;
        dibujar();
      });
    }).observe(lienzo);
    dibujar();
  }

  document.querySelectorAll("[data-historial]").forEach(iniciar);
})();
