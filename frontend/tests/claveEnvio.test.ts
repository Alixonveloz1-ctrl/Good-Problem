/**
 * La clave retenida de la pantalla de la Biblia, probada fuera del
 * navegador: la misma clave sobrevive a los envios que no devuelven
 * trabajo, y solo tras un envio con exito toca una clave nueva.
 *
 * Se corre con el node del sistema (sin dependencias):
 *   npm test        (desde frontend/)
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { ClaveDeEnvio } from '../src/lib/claveEnvio.ts'

function fabricaContadora(): () => string {
  let n = 0
  return () => `clave-${++n}`
}

test('la misma clave sobrevive a los envios que no devuelven trabajo', () => {
  const clave = new ClaveDeEnvio(fabricaContadora())
  const primera = clave.paraEnviar()
  // Dos toques cuya respuesta se perdio (a los 45 segundos, sin
  // trabajo a la vista): el siguiente envio manda la MISMA clave, y
  // el servidor devuelve el trabajo que ya habia creado.
  assert.equal(clave.paraEnviar(), primera)
  assert.equal(clave.paraEnviar(), primera)
})

test('tras un envio con exito, el siguiente encargo usa otra clave', () => {
  const clave = new ClaveDeEnvio(fabricaContadora())
  const primera = clave.paraEnviar()
  clave.conseguida()
  const segunda = clave.paraEnviar()
  assert.notEqual(segunda, primera)
  // Y la nueva tambien se retiene hasta que su encargo tenga exito.
  assert.equal(clave.paraEnviar(), segunda)
})
