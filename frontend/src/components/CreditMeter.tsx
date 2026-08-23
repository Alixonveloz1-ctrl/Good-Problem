import { money } from '../api/client'
import type { Budget } from '../api/types'

/**
 * Credit left and days left (PRD 44).
 *
 * The $300 welcome credit expires 90 days after sign up whether or not it is
 * spent, so the calendar matters as much as the balance.
 */
export function CreditMeter({ budget }: { budget: Budget }) {
  const used = budget.total_usd > 0 ? budget.spent_usd / budget.total_usd : 0
  const low = used > 0.8 || (budget.credit_days_left !== null && budget.credit_days_left <= 14)
  return (
    <div className="credit">
      <div className="row between">
        <span className="muted">Credito restante</span>
        {budget.hard_stop && <span className="badge accent">Corte automatico</span>}
      </div>
      <div className="amount">{money(budget.remaining_usd)}</div>
      <div className={`meter ${low ? 'low' : ''}`}>
        <span style={{ width: `${Math.min(100, Math.round(used * 100))}%` }} />
      </div>
      <div className="row between muted">
        <span>
          {money(budget.spent_usd)} de {money(budget.total_usd)}
        </span>
        <span>
          {budget.credit_days_left === null
            ? 'sin fecha de caducidad'
            : budget.credit_days_left < 0
              ? 'credito caducado'
              : `caduca en ${budget.credit_days_left} dias`}
        </span>
      </div>
    </div>
  )
}
