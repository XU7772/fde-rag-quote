import { fmt, useCountUp, useTypewriter } from '../lib'

const LEVEL_LABEL = { error: '阻断', warn: '提示', info: '记录' }

function Change({ pct }) {
  if (pct == null) return <span className="muted">无历史</span>
  const up = pct > 0
  return (
    <span className={`change ${up ? 'up' : 'down'}`}>
      {up ? '↑' : '↓'} {Math.abs(pct).toFixed(1)}%
    </span>
  )
}

/** 参考价：p50 + 本次偏离。检索不到时什么都不显示，不占位。 */
function ReferenceHint({ reference, deviation }) {
  if (!reference?.available) return null
  return (
    <small className="ref-hint">
      参考 {fmt(reference.p50)}
      {deviation != null && (
        <span className={`ref-dev ${deviation > 0 ? 'up' : 'down'}`}>
          {deviation > 0 ? '+' : ''}
          {deviation.toFixed(1)}%
        </span>
      )}
    </small>
  )
}

function Checks({ violations }) {
  return (
    <section className="checks">
      <div className="panel-head">
        <span>工艺校验</span>
        <span className="mono">RULES.MD → 确定性判断</span>
      </div>

      {violations.length === 0 ? (
        <p className="checks-empty">全部规则通过 · 未发现工艺冲突</p>
      ) : (
        <ul className="checks-list">
          {violations.map((v, index) => (
            <li className={`check ${v.level}`} key={`${v.rule_id}-${index}`}>
              <span className="check-id mono">{v.rule_id}</span>
              <span className="check-body">
                <b>{v.part_name}</b>
                {v.message}
              </span>
              <span className="check-level mono">{LEVEL_LABEL[v.level] ?? v.level}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function Result({ quote, summary, order, onDownload, onReset }) {
  const total = useCountUp(quote.total)
  const typed = useTypewriter(summary)
  const lineSubtotal = quote.line_items.reduce((sum, row) => sum + row.line_total, 0)

  const violations = quote.violations ?? []
  const blocking = violations.filter((v) => v.level === 'error')
  const blocked = quote.blocked || blocking.length > 0

  const compared = quote.line_items.filter((row) => row.deviation_pct != null)
  const biggestDev = compared.sort(
    (a, b) => Math.abs(b.deviation_pct) - Math.abs(a.deviation_pct),
  )[0]

  return (
    <main className="result">
      <div className="result-top">
        <div className="result-title">
          <p className="eyebrow">QUOTATION READY · {order.inquiry_no || 'DEMO'}</p>
          <div className="total">
            <span className="cny">¥</span>
            {fmt(total)}
          </div>
          <p className="total-meta">
            {quote.item_count} 个零件 · {quote.total_quantity} 件 · 含开机费 ¥{fmt(quote.setup_fee)}
            {quote.expedite ? ` · 急单系数 ${quote.expedite_multiplier}` : ''}
          </p>
        </div>

        <div className="output-block">
          <span className="output-label">OUTPUT · 报价单已生成</span>
          <div className="result-actions">
            <button
              className="btn primary"
              onClick={onDownload}
              type="button"
              disabled={blocked}
            >
              下载 PDF 报价单 <span className="btn-arrow">↓</span>
            </button>
            <button className="btn ghost" onClick={onReset} type="button">
              重新演示
            </button>
          </div>
          <span className="output-note">
            {blocked ? '存在阻断级问题 · 需修正后才能出单' : '后端 fpdf2 生成 · A4 · 可直接发客户'}
          </span>
        </div>
      </div>

      {blocked && (
        <p className="block-banner">
          <b>已阻断</b>
          存在 {blocking.length} 条阻断级工艺问题，规则未通过前不会生成报价单。
        </p>
      )}

      <div className="result-grid">
        <section className="quote-sheet">
          <div className="panel-head">
            <span>报价明细</span>
            <span className="mono">DETERMINISTIC / PYTHON</span>
          </div>

          <table>
            <thead>
              <tr>
                <th>零件</th>
                <th>材质</th>
                <th className="num">数量</th>
                <th className="num">单件价</th>
                <th className="num">小计</th>
                <th className="num">较上次</th>
              </tr>
            </thead>
            <tbody>
              {quote.line_items.map((row) => (
                <tr key={row.part_name}>
                  <td>
                    <b>{row.part_name}</b>
                    <small>{row.process}</small>
                  </td>
                  <td>{row.material}</td>
                  <td className="num">
                    {row.quantity} {row.unit}
                  </td>
                  <td className="num">
                    ¥{fmt(row.unit_price)}
                    <ReferenceHint reference={row.reference} deviation={row.deviation_pct} />
                  </td>
                  <td className="num">¥{fmt(row.line_total)}</td>
                  <td className="num">
                    <Change pct={row.change_pct} />
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan="4">零件合计</td>
                <td className="num">¥{fmt(lineSubtotal)}</td>
                <td />
              </tr>
              <tr>
                <td colSpan="4">开机费</td>
                <td className="num">¥{fmt(quote.setup_fee)}</td>
                <td />
              </tr>
              <tr className="grand">
                <td colSpan="4">合计</td>
                <td className="num">¥{fmt(quote.total)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </section>

        <section className="summary-card">
          <div className="panel-head">
            <span>报价摘要</span>
            <span className="mono">FACTS → LLM</span>
          </div>

          <p className="summary-text">
            {typed}
            <span className="caret">▌</span>
          </p>

          <div className="summary-foot">数字由 Python 计算 · 文字由 deepseek-flash 组织</div>

          <div className="source-facts">
            <div>
              <span>历史对比</span>
              <b>
                {quote.biggest_change
                  ? `${quote.biggest_change.part_name} ${
                      quote.biggest_change.change_pct > 0 ? '+' : ''
                    }${quote.biggest_change.change_pct}%`
                  : '无历史同材料报价'}
              </b>
            </div>
            <div>
              <span>参考价偏离</span>
              <b>
                {biggestDev
                  ? `${biggestDev.part_name} ${biggestDev.deviation_pct > 0 ? '+' : ''}${biggestDev.deviation_pct}%`
                  : '无相似历史'}
              </b>
            </div>
            <div>
              <span>工艺校验</span>
              <b>{violations.length ? `${violations.length} 项` : '全部通过'}</b>
            </div>
            <div>
              <span>计价方式</span>
              <b>材料费 + 工序费</b>
            </div>
          </div>
        </section>
      </div>

      <Checks violations={violations} />
    </main>
  )
}
