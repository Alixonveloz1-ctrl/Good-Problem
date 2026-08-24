import { useMemo, useState } from 'react'
import { useResource } from '../hooks/useApi'
import type { ModelSpec, Registry, Variant } from '../api/types'
import { Sheet } from './ui'

export interface ModelChoice {
  model: string
  variant: string
  label: string
  unit: string
}

/**
 * The model selector (PRD 16, 39).
 *
 * Una hoja que sube desde abajo, desde cualquier pantalla de generacion. La
 * musica no tiene selector: hay un solo modelo.
 *
 * No se habla de dinero aqui. El gasto se mira en la consola de Google Cloud,
 * que es donde esta el de verdad; repetirlo en la app solo anade una cifra que
 * hay que mantener al dia y que nadie va a creerse.
 */
export function ModelPicker({
  kind,
  value,
  onChange,
  seconds = 8,
  label = 'Modelo',
}: {
  kind: 'image' | 'video' | 'text' | 'speech'
  value: ModelChoice | null
  onChange: (choice: ModelChoice) => void
  seconds?: number
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const { data } = useResource<Registry>('/api/registry/models')

  const models = useMemo(
    () => (data?.models ?? []).filter((model) => model.kind === kind),
    [data, kind],
  )

  const excluded = useMemo(
    () => (data?.excluded ?? []).filter((entry) => entry.kind === kind),
    [data, kind],
  )

  const select = (model: ModelSpec, variant: Variant) => {
    onChange({
      model: model.id,
      variant: variant.key,
      label: `${model.label} · ${variant.label}`,
      unit: variant.unit,
    })
    setOpen(false)
  }

  return (
    <>
      <button className="btn block" onClick={() => setOpen(true)} type="button">
        <span className="grow" style={{ textAlign: 'left' }}>
          {label}: {value ? value.label : 'elegir'}
        </span>
        <span className="muted">›</span>
      </button>

      {open && (
        <Sheet title={`Elegir modelo de ${kindLabel(kind)}`} onClose={() => setOpen(false)}>
          {kind === 'video' && (
            <p className="muted" style={{ margin: 0 }}>
              Todos generan un plano de {seconds} segundos a partir de la imagen
              aprobada, con el audio desactivado.
            </p>
          )}
          {models.map((model) => (
            <div
              key={model.id}
              className={`model-option ${value?.model === model.id ? 'selected' : ''}`}
            >
              <div className="row between">
                <div>
                  <div style={{ fontWeight: 600 }}>{model.label}</div>
                  <div className="mono muted">{model.id}</div>
                </div>
                {capabilityBadge(model)}
              </div>
              <div className="variant-row">
                {model.variants.map((variant) => (
                  <button
                    key={variant.key}
                    type="button"
                    className={`variant ${
                      value?.model === model.id && value.variant === variant.key ? 'selected' : ''
                    }`}
                    onClick={() => select(model, variant)}
                  >
                    <span>{variant.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}

          {excluded.length > 0 && (
            <>
              <div className="section-title">Fuera del sistema</div>
              {excluded.map((entry) => (
                <div key={entry.id} className="notice">
                  <strong className="mono">{entry.id}</strong>
                  <div>{entry.reason}</div>
                </div>
              ))}
            </>
          )}
        </Sheet>
      )}
    </>
  )
}

function kindLabel(kind: string): string {
  return kind === 'image' ? 'imagen' : kind === 'video' ? 'video' : kind
}

function capabilityBadge(model: ModelSpec) {
  const characters = Number(model.capabilities.reference_characters_max ?? -1)
  if (model.kind === 'image') {
    if (characters === 0) {
      return <span className="badge rejected">Sin referencia de personaje</span>
    }
    if (characters > 0) {
      return <span className="badge approved">{characters} personajes</span>
    }
  }
  return null
}
