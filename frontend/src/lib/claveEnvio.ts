/**
 * La clave de idempotencia de UN encargo, retenida entre intentos.
 *
 * El servidor crea el trabajo y lo recuerda por la clave ANTES de
 * contestar. Si la respuesta se pierde por el camino —el telefono corta
 * a los 45 segundos y el servidor si llego a crear el trabajo—, un
 * segundo toque con una clave NUEVA no encuentra aquel trabajo: en el
 * mejor de los casos duplica el encargo, y en el peor el usuario se
 * queda sin nada que mirar, sin trabajo y sin error.
 *
 * Con la MISMA clave, el segundo toque devuelve ESE trabajo. Por eso la
 * clave se conserva mientras el encargo no se ha conseguido, y solo se
 * renueva cuando un envio ya devolvio su trabajo: el siguiente encargo
 * es otro encargo, y lleva otra clave.
 */
export class ClaveDeEnvio {
  private actual: string | null = null
  private readonly fabrica: () => string

  constructor(fabrica: () => string) {
    this.fabrica = fabrica
  }

  /** La clave a enviar ahora: la retenida, o una nueva si no hay ninguna. */
  paraEnviar(): string {
    if (this.actual === null) {
      this.actual = this.fabrica()
    }
    return this.actual
  }

  /** Un envio devolvio su trabajo: el proximo encargo usa clave nueva. */
  conseguida(): void {
    this.actual = null
  }
}
