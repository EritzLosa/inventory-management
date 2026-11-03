<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="loadError" class="error">{{ loadError }}</div>
    <div v-else>
      <div v-if="successOrder" class="success-banner">
        {{ t('restocking.success', { orderNumber: successOrder.order_number }) }}
        <router-link to="/orders">{{ t('restocking.viewOrder') }}</router-link>
      </div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card budget-card">
        <label class="budget-label" for="budget-range">{{ t('restocking.budgetLabel') }}</label>
        <div class="budget-control">
          <input
            id="budget-range"
            v-model.number="budget"
            type="range"
            min="0"
            :max="maxBudget"
            step="100"
            :disabled="submitting"
          />
          <span class="budget-value">{{ formatCurrency(budget, currentCurrency) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(budget, currentCurrency) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.totalCost') }}</div>
          <div class="stat-value">{{ formatCurrency(totalCost, currentCurrency) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatCurrency(remaining, currentCurrency) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsSelected') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header header-row">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div v-if="recommendations.length === 0" class="empty-state">{{ t('restocking.empty') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.item') }}</th>
                <th>{{ t('restocking.trend') }}</th>
                <th>{{ t('restocking.quantity') }}</th>
                <th>{{ t('restocking.unitCost') }}</th>
                <th>{{ t('restocking.lineTotal') }}</th>
                <th>{{ t('restocking.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="line in recommendations" :key="line.item_sku">
                <td>
                  <strong>{{ line.item_name }}</strong>
                  <div class="sku">{{ line.item_sku }}</div>
                </td>
                <td>
                  <span :class="['badge', line.trend]">{{ t(`trends.${line.trend}`) }}</span>
                </td>
                <td>{{ line.quantity.toLocaleString() }}</td>
                <td>{{ formatCurrencyWithDecimals(line.unit_cost, currentCurrency, 2) }}</td>
                <td><strong>{{ formatCurrency(line.line_total, currentCurrency) }}</strong></td>
                <td>{{ line.lead_time_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const TREND_PRIORITY = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const loading = ref(true)
    const loadError = ref(null)
    const submitError = ref(null)
    const submitting = ref(false)
    const successOrder = ref(null)
    const forecasts = ref([])
    const budget = ref(0)

    const changePct = (f) => {
      if (!f.current_demand) return 0
      return (f.forecasted_demand - f.current_demand) / f.current_demand
    }

    const candidates = computed(() => {
      return forecasts.value
        .filter(f => f.forecasted_demand > 0 && f.unit_cost > 0)
        .map(f => ({ ...f, quantity: f.forecasted_demand }))
        .sort((a, b) => {
          const pa = TREND_PRIORITY[a.trend] ?? 3
          const pb = TREND_PRIORITY[b.trend] ?? 3
          if (pa !== pb) return pa - pb
          return changePct(b) - changePct(a)
        })
    })

    const maxBudget = computed(() => {
      return Math.ceil(candidates.value.reduce((sum, c) => sum + c.quantity * c.unit_cost, 0))
    })

    const recommendations = computed(() => {
      let remainingBudget = budget.value
      const lines = []
      for (const c of candidates.value) {
        let quantity = 0
        if (c.quantity * c.unit_cost <= remainingBudget) {
          quantity = c.quantity
        } else {
          const partial = Math.floor(remainingBudget / c.unit_cost)
          if (partial >= 1) quantity = partial
        }
        if (quantity < 1) continue
        const lineTotal = quantity * c.unit_cost
        remainingBudget -= lineTotal
        lines.push({
          item_sku: c.item_sku,
          item_name: c.item_name,
          trend: c.trend,
          quantity,
          unit_cost: c.unit_cost,
          line_total: lineTotal,
          lead_time_days: c.lead_time_days
        })
      }
      return lines
    })

    const totalCost = computed(() => recommendations.value.reduce((sum, l) => sum + l.line_total, 0))
    const remaining = computed(() => Math.max(0, budget.value - totalCost.value))

    const loadForecasts = async () => {
      try {
        loading.value = true
        forecasts.value = await api.getDemandForecasts()
        budget.value = Math.round(maxBudget.value * 0.5 / 100) * 100
      } catch (err) {
        loadError.value = 'Failed to load demand forecasts: ' + err.message
      } finally {
        loading.value = false
      }
    }

    // Clear stale success banner when the user changes the plan
    watch(budget, () => {
      successOrder.value = null
    })

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      successOrder.value = null
      try {
        const order = await api.createRestockOrder({
          budget: budget.value,
          items: recommendations.value.map(({ item_sku, quantity }) => ({ item_sku, quantity }))
        })
        successOrder.value = order
      } catch (err) {
        submitError.value = err.response?.data?.detail || t('restocking.error')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      currentCurrency,
      formatCurrency,
      formatCurrencyWithDecimals,
      loading,
      loadError,
      submitError,
      submitting,
      successOrder,
      budget,
      maxBudget,
      candidates,
      recommendations,
      totalCost,
      remaining,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 0.75rem;
}

.budget-control {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.budget-control input[type='range'] {
  flex: 1;
}

.budget-value {
  min-width: 120px;
  text-align: right;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.place-order-btn {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-banner {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}

.success-banner a {
  margin-left: 0.5rem;
  color: #15803d;
  font-weight: 600;
}

.sku {
  font-size: 0.813rem;
  color: #64748b;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}
</style>
