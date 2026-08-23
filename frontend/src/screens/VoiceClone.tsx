import { useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useAction, useResource } from '../hooks/useApi'
import { Grabadora, aBase64, aWav24k, grabacionDisponible, urlDeReproduccion } from '../lib/audio'
import { Card, ErrorNote, Loading, TopBar } from '../components/ui'

interface Estado {
  ready: boolean
  secret_name: string | null
  consent_script: string
  sample_seconds: number
}

interface Toma {
  bytes: Uint8Array
  url: string
  segundos: number
}

/**
 * Clonar la voz hablada del artista (PRD 4, 34, 35).
 *
 * Con esta voz suenan igual las entrevistas, el BTS y el diario del artista.
 * Sin ella, el boton de voz en Contenido no puede funcionar.
 *
 * Google pide dos grabaciones: una muestra de unos diez segundos y una frase de
 * consentimiento leida palabra por palabra.
 */
export function VoiceCloneScreen() {
  const { universeId = '' } = useParams()
  const base = `/api/universes/${universeId}/content/voice-clone`
  const { data, loading, error, reload } = useResource<Estado>(base)
  const action = useAction()
  const [muestra, setMuestra] = useState<Toma | null>(null)
  const [consentimiento, setConsentimiento] = useState<Toma | null>(null)
  const [listo, setListo] = useState(false)

  const crear = async () => {
    if (!muestra || !consentimiento) return
    const hecho = await action.run(() =>
      api.post(base, {
        sample_base64: aBase64(muestra.bytes),
        consent_base64: aBase64(consentimiento.bytes),
        language_code: 'es-ES',
      }),
    )
    if (hecho) {
      setListo(true)
      await reload()
    }
  }

  return (
    <>
      <TopBar title="Voz del artista" back />
      <main className="screen">
        {loading && !data && <Loading />}
        <ErrorNote error={error ?? action.error} onDismiss={action.clearError} />

        {data?.ready && !listo && (
          <div className="notice">
            Este artista ya tiene voz clonada. Si grabas otra, sustituira a la anterior y todo lo
            que generes a partir de ahora sonara distinto.
          </div>
        )}
        {listo && (
          <div className="notice" style={{ borderColor: 'var(--ok)', color: 'var(--ok)' }}>
            Voz creada. Ya puedes generar entrevistas y BTS con ella.
          </div>
        )}

        <Card>
          <h3>Para que sirve</h3>
          <p className="muted" style={{ margin: 0 }}>
            Es la voz con la que habla tu artista: entrevistas, detras de camaras, anuncios. Se
            graba una sola vez y a partir de ahi suena siempre igual.
          </p>
          <p className="muted" style={{ margin: 0 }}>
            La voz <strong>cantada</strong> no sale de aqui: esa la pone Lyria en cada cancion.
          </p>
        </Card>

        {!grabacionDisponible() && (
          <div className="error">
            Este navegador no deja grabar. Abre la app en Safari y dale permiso al microfono.
          </div>
        )}

        <Card>
          <h3>1 · La voz</h3>
          <p className="muted" style={{ margin: 0 }}>
            Graba unos {data?.sample_seconds ?? 10} segundos hablando con naturalidad. Di lo que
            quieras: como se llama tu artista, de donde es, lo que le apetece contar. Busca un sitio
            en silencio.
          </p>
          <Grabador etiqueta="la voz" onListo={setMuestra} toma={muestra} />
        </Card>

        <Card>
          <h3>2 · El permiso</h3>
          <p className="muted" style={{ margin: 0 }}>
            Google exige esta frase para dejarte clonar una voz. Hay que leerla tal cual, en ingles,
            sin cambiar ni una palabra:
          </p>
          <pre className="block wrap">{data?.consent_script ?? ''}</pre>
          <Grabador etiqueta="el permiso" onListo={setConsentimiento} toma={consentimiento} />
        </Card>

        <button
          className="btn primary block"
          disabled={!muestra || !consentimiento || action.busy}
          onClick={crear}
        >
          {action.busy ? 'Creando la voz…' : 'Crear la voz'}
        </button>

        <p className="muted" style={{ margin: 0 }}>
          Las dos grabaciones van a Google, que devuelve una llave. La llave se guarda a buen
          recaudo y es lo unico secreto que hay en todo el proyecto. Los audios no se quedan aqui.
        </p>
      </main>
    </>
  )
}

function Grabador({
  etiqueta,
  toma,
  onListo,
}: {
  etiqueta: string
  toma: Toma | null
  onListo: (toma: Toma) => void
}) {
  const grabadora = useRef(new Grabadora())
  const [grabando, setGrabando] = useState(false)
  const [procesando, setProcesando] = useState(false)
  const [fallo, setFallo] = useState<string | null>(null)

  const alternar = async () => {
    setFallo(null)
    try {
      if (!grabando) {
        await grabadora.current.empezar()
        setGrabando(true)
        return
      }
      setGrabando(false)
      setProcesando(true)
      const grabacion = await grabadora.current.parar()
      const bytes = await aWav24k(grabacion.blob)
      onListo({ bytes, url: urlDeReproduccion(bytes), segundos: grabacion.segundos })
    } catch (caught) {
      setFallo(
        caught instanceof Error && caught.name === 'NotAllowedError'
          ? 'No diste permiso al microfono. Vuelve a intentarlo y acepta.'
          : `No se pudo grabar ${etiqueta}.`,
      )
      setGrabando(false)
    } finally {
      setProcesando(false)
    }
  }

  return (
    <>
      <button
        className={`btn block ${grabando ? 'danger' : ''}`}
        onClick={alternar}
        disabled={procesando}
      >
        {procesando ? 'Preparando…' : grabando ? '■  Parar' : toma ? 'Grabar otra vez' : '●  Grabar'}
      </button>
      {fallo && <div className="error">{fallo}</div>}
      {toma && (
        <>
          <audio controls src={toma.url} />
          <div className="muted">Grabados {toma.segundos.toFixed(1)} segundos. Escuchalo antes de seguir.</div>
        </>
      )}
    </>
  )
}
