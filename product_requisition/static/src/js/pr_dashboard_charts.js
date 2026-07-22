/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, useEffect, useRef } from "@odoo/owl";

// ─── Status Doughnut Chart ────────────────────────────────────────────────────

class PrStatusDonut extends Component {
    static template = "product_requisition.PrStatusDonut";
    static props = { ...standardFieldProps };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;

        onWillStart(async () => await loadBundle("web.chartjs_lib"));

        useEffect(() => {
            this._render();
            // Chart.js measures container width at render time, but flex panels
            // may not have their final width yet — force a resize after layout.
            const raf = requestAnimationFrame(() => {
                if (this.chart) this.chart.resize();
            });
            return () => {
                cancelAnimationFrame(raf);
                if (this.chart) {
                    this.chart.destroy();
                    this.chart = null;
                }
            };
        });
    }

    get chartData() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return null;
        try { return JSON.parse(raw); } catch (_) { return null; }
    }

    _render() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        const d = this.chartData;
        if (!d || !this.canvasRef.el) return;

        // Filter out zero-value slices
        const filtered = d.labels.map((l, i) => ({ label: l, value: d.values[i], color: d.colors[i] }))
                                  .filter(x => x.value > 0);

        const labels = filtered.length ? filtered.map(x => x.label) : ["No Data"];
        const values = filtered.length ? filtered.map(x => x.value) : [1];
        const colors = filtered.length ? filtered.map(x => x.color) : ["#e2e8f0"];

        this.chart = new Chart(this.canvasRef.el, {
            type: "doughnut",
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderWidth: 3,
                    borderColor: "#f8fafc",
                    hoverBorderColor: "#ffffff",
                    hoverOffset: 8,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "68%",
                layout: {
                    padding: { 
                        top: 5, 
                        bottom: 5, 
                        left: 5, 
                        right: 5 
                    }
                },
                animation: { animateRotate: true, duration: 700 },
                plugins: {
                    legend: {
                        position: "bottom",
                        align: "center",
                        labels: {
                            padding: 16,
                            font: { size: 12, family: "'Inter', sans-serif" },
                            usePointStyle: true,
                            pointStyle: "circle",
                            boxWidth: 12,
                            boxHeight: 12,
                            color: "#334155",
                        },
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                                const pct = total ? Math.round(ctx.parsed / total * 100) : 0;
                                return `  ${ctx.label}: ${ctx.parsed}  (${pct}%)`;
                            },
                        },
                    },
                },
            },
        });
    }
}

// ─── Monthly Line/Bar Chart ────────────────────────────────────────────────────

class PrMonthlyLine extends Component {
    static template = "product_requisition.PrMonthlyLine";
    static props = { ...standardFieldProps };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;

        onWillStart(async () => await loadBundle("web.chartjs_lib"));

        useEffect(() => {
            this._render();
            const raf = requestAnimationFrame(() => {
                if (this.chart) this.chart.resize();
            });
            return () => {
                cancelAnimationFrame(raf);
                if (this.chart) {
                    this.chart.destroy();
                    this.chart = null;
                }
            };
        });
    }

    get chartData() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return null;
        try { return JSON.parse(raw); } catch (_) { return null; }
    }

    _render() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        const d = this.chartData;
        if (!d || !this.canvasRef.el) return;

        this.chart = new Chart(this.canvasRef.el, {
            type: "line",
            data: {
                labels: d.labels,
                datasets: [
                    {
                        label: "Total",
                        data: d.counts,
                        borderColor: "#3b82f6",
                        backgroundColor: "rgba(59,130,246,0.10)",
                        fill: true,
                        tension: 0.4,
                        borderWidth: 2.5,
                        pointBackgroundColor: "#3b82f6",
                        pointBorderColor: "#ffffff",
                        pointBorderWidth: 2,
                        pointRadius: 5,
                        pointHoverRadius: 7,
                    },
                    {
                        label: "Approved",
                        data: d.approved,
                        borderColor: "#10b981",
                        backgroundColor: "transparent",
                        fill: false,
                        tension: 0.4,
                        borderWidth: 2,
                        borderDash: [5, 4],
                        pointBackgroundColor: "#10b981",
                        pointBorderColor: "#ffffff",
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                    },
                    {
                        label: "Rejected",
                        data: d.rejected,
                        borderColor: "#ef4444",
                        backgroundColor: "transparent",
                        fill: false,
                        tension: 0.4,
                        borderWidth: 2,
                        borderDash: [3, 4],
                        pointBackgroundColor: "#ef4444",
                        pointBorderColor: "#ffffff",
                        pointBorderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                animation: { duration: 700 },
                plugins: {
                    legend: {
                        position: "top",
                        align: "end",
                        labels: {
                            font: { size: 12, family: "'Inter', sans-serif" },
                            usePointStyle: true,
                            pointStyleWidth: 10,
                            boxHeight: 10,
                            padding: 16,
                            color: "#334155",
                        },
                    },
                    tooltip: {
                        mode: "index",
                        intersect: false,
                        backgroundColor: "rgba(15,23,42,0.85)",
                        titleColor: "#f1f5f9",
                        bodyColor: "#cbd5e1",
                        padding: 10,
                        cornerRadius: 6,
                    },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: "rgba(148,163,184,0.14)" },
                        ticks: {
                            stepSize: 1,
                            font: { size: 11 },
                            color: "#64748b",
                        },
                        border: { display: false },
                    },
                    x: {
                        grid: { display: false },
                        ticks: {
                            font: { size: 11 },
                            color: "#64748b",
                            maxRotation: 30,
                        },
                        border: { color: "rgba(148,163,184,0.2)" },
                    },
                },
            },
        });
    }
}

// ─── Registry Registration ─────────────────────────────────────────────────────

export const prStatusDonut = {
    component: PrStatusDonut,
    supportedTypes: ["text"],
};

export const prMonthlyLine = {
    component: PrMonthlyLine,
    supportedTypes: ["text"],
};

registry.category("fields").add("pr_status_donut", prStatusDonut);
registry.category("fields").add("pr_monthly_line", prMonthlyLine);

// ─── Department Breakdown Table ───────────────────────────────────────────────

class PrDeptTable extends Component {
    static template = "product_requisition.PrDeptTable";
    static props = { ...standardFieldProps };

    get rows() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return [];
        try { return JSON.parse(raw); } catch (_) { return []; }
    }
}

// ─── Purchase Type Breakdown Table ───────────────────────────────────────────

class PrTypeTable extends Component {
    static template = "product_requisition.PrTypeTable";
    static props = { ...standardFieldProps };

    get rows() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return [];
        try { return JSON.parse(raw); } catch (_) { return []; }
    }
}

// ─── Recent Requisitions Table ────────────────────────────────────────────────

class PrRecentTable extends Component {
    static template = "product_requisition.PrRecentTable";
    static props = { ...standardFieldProps };

    get rows() {
        const raw = this.props.record.data[this.props.name];
        if (!raw) return [];
        try { return JSON.parse(raw); } catch (_) { return []; }
    }

    stateClass(stateKey) {
        const map = {
            draft: "o_pr_badge_draft",
            submitted: "o_pr_badge_submitted",
            in_approval: "o_pr_badge_approval",
            approved: "o_pr_badge_approved",
            rejected: "o_pr_badge_rejected",
            cancelled: "o_pr_badge_cancelled",
            rfq_created: "o_pr_badge_rfq",
            done: "o_pr_badge_done",
        };
        return map[stateKey] || "o_pr_badge_draft";
    }

    formatCost(val) {
        if (!val) return "—";
        return val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
}

export const prDeptTable   = { component: PrDeptTable,   supportedTypes: ["text"] };
export const prTypeTable   = { component: PrTypeTable,   supportedTypes: ["text"] };
export const prRecentTable = { component: PrRecentTable, supportedTypes: ["text"] };

registry.category("fields").add("pr_dept_table",   prDeptTable);
registry.category("fields").add("pr_type_table",   prTypeTable);
registry.category("fields").add("pr_recent_table", prRecentTable);
