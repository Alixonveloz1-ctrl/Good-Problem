import { useMemo, useState } from 'react'
import { useResource } from '../hooks/useApi'
import type { ModelSpec, Registry, Variant } from '../api/types'
import { Sheet } from './ui'

export interface ModelChoice {
  model: string
  variant: string
  label: string
  price: number
  unit: string
}

function priceOf(variant: Variant): number {
  return variant.price ?? 0
}

function unitLabel(unit: string): string {
  switch (unit) {
    case 'second':
      return 'por segundo'
    case 'image':
      return 'por imagen'
    case 'song':
      return 'por cancion'
    case '1m_characters':
      return 'por millon de caracteres'
    default:
      return ''
  }
}

function formatPrice(variant: Variant): string {
  const price = priceOf(variant)
  const digits = price < 0.1 ? 3 : 2
  return `$${price.toFixed(digits)}`
}

/** Estimated total for one generation, so the price is visible before tapping. */
function estimate(kind: string, variant: Variant, seconds: number): string {
  if (kind === 'video') return `$${(priceOf(variant) * seconds).toFixed(2)} / clip de ${seconds}s`
  return `${formatPrice(variant)} ${unitLabel(variant.unit)}`
}

/**
 * The model selector (PRD 16, 39).
 *
 * A bottom sheet reachable from any generation screen, with the price of every
 * option visible in the list. Music has no selector: there is one model.
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
      price: priceOf(variant),
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
        <span className="muted">
          {value && kind === 'video'
            ? `$${(value.price * seconds).toFixed(2)}`
            : value
              ? `$${value.price.toFixed(value.price < 0.1 ? 3 : 2)}`
              : '›'}
        </span>
      </button>

      {open && (
        <Sheet title={`Elegir modelo de ${kindLabel(kind)}`} onClose={() => setOpen(false)}>
          <p className="muted" style={{ margin: 0 }}>
            {kind === 'video'
              ? 'El precio es el del clip completo. Veo cobra por segundo, no por video: 8 s a $0,05 el segundo son $0,40. El audio va siempre desactivado.'
              : 'El precio de cada opcion es el de una generacion.'}
          </p>
          {kind === 'video' && (
            <p className="muted" style={{ margin: 0 }}>
              Todas las escenas duran 8 segundos. «Alarga tomas» significa que ese modelo puede
              continuar un plano ya generado, +7 s cada vez, hasta unos 148 s; «Solo 8 s» que no
              puede. El estudio todavia no usa esa funcion, asi que hoy la diferencia no te afecta.
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
                    <span className="price">{estimate(kind, variant, seconds)}</span>
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
  if (model.kind === 'video') {
    // "Extension" no le dice nada a nadie: lo que cambia es si el modelo puede
    // continuar un plano mas alla de los 8 segundos.
    return model.capabilities.supports_extend ? (
      <span className="badge">Alarga tomas</span>
    ) : (
      <span className="badge">Solo 8 s</span>
    )
  }
  return null
}
