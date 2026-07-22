/** @odoo-module */

import { Component, onMounted, useRef, onWillUnmount, useState, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class BurndownChart extends Component {
    setup() {
        this.orm = useService("orm");
        this.canvasRef = useRef("burndownCanvas");
        this.chartInstance = null;

        // Reactive state:
        // loading            — shows spinner while fetching
        // error              — shows error banner if fetch or render fails
        // allData            — full bulk dataset from server (all sprints + their snapshots)
        // selectedSprintId   — currently selected sprint ID (driven by dropdown)
        // selectedSprintData — full sprint object for the selected sprint
        // metrics            — KPI indicators: total, completed, remaining, progress %
        this.state = useState({
            loading: false,
            error: null,
            allData: [],
            selectedSprintId: null,
            selectedSprintData: null,
            metrics: {
                totalPoints: 0,
                remainingPoints: 0,
                completedPoints: 0,
                percentComplete: 0
            }
        });

        onMounted(async () => {
            // Only load Chart.js if not already loaded (velocity chart may have loaded it first)
            if (!window.Chart) {
                await loadJS("/web/static/lib/Chart/Chart.js");
            }
            if (this.props.projectId) await this.fetchAllData(this.props.projectId);
        });

        onWillUpdateProps(async (nextProps) => {
            // Project changed in the sidebar — reset everything and re-fetch
            if (nextProps.projectId !== this.props.projectId) {
                this.state.allData = [];
                this.state.selectedSprintId = null;
                this.state.selectedSprintData = null;
                this.state.error = null;
                if (this.chartInstance) {
                    this.chartInstance.destroy();
                    this.chartInstance = null;
                }
                await this.fetchAllData(nextProps.projectId);
            }
        });

        onWillUnmount(() => {
            // Destroy Chart.js instance to prevent canvas memory leaks
            if (this.chartInstance) this.chartInstance.destroy();
        });
    }

    // ==========================================
    // FETCH — one server call, all sprints + snapshots
    // Backend returns sprints ordered start_date asc
    // so allData[last] is always the latest sprint.
    // After fetch: auto-selects latest sprint and
    // renders chart after 300ms to give OWL time
    // to inject the canvas element into the DOM.
    // ==========================================
    async fetchAllData(projectId = this.props.projectId) {
        if (!projectId) return;
        this.state.loading = true;
        this.state.error = null;
        try {
            // Calls get_burndown_chart_data on project.sprint.burndown.snapshot model
            const data = await this.orm.call(
                "project.sprint.burndown.snapshot",
                "get_burndown_chart_data",
                [],
                { project_id: projectId }
            );
            this.state.allData = Array.isArray(data) ? data : [];

            // Auto-select the latest sprint (last in asc-sorted array = most recent)
            const latest = this.state.allData.length
                ? this.state.allData[this.state.allData.length - 1]
                : null;

            if (latest) {
                this.state.selectedSprintId = latest.sprint_id;
                this.state.selectedSprintData = latest;
                this.calculateMetrics(latest);
                // 300ms delay: OWL needs to re-render the t-elif block
                // and inject the canvas into the DOM before Chart.js can draw on it
                setTimeout(() => this.buildOrUpdateChart(latest), 300);
            }
        } catch (e) {
            console.error("Burndown Chart Fetch Error:", e);
            this.state.error = "Failed to load burndown data. Please refresh.";
        }
        this.state.loading = false;
    }

    // ==========================================
    // SPRINT CHANGE — triggered by dropdown.
    // Pure JS — no server call.
    // Looks up the sprint in allData by ID,
    // recalculates metrics and updates chart smoothly.
    // ==========================================
    onSprintChange(ev) {
        const sprintId = parseInt(ev.target.value);
        const sprint = this.state.allData.find(s => s.sprint_id === sprintId);
        if (!sprint) return;

        this.state.selectedSprintId = sprintId;
        this.state.selectedSprintData = sprint;
        this.calculateMetrics(sprint);
        this.buildOrUpdateChart(sprint); // no setTimeout needed — canvas already in DOM
    }

    // ==========================================
    // METRICS — derives KPI values from the
    // selected sprint's snapshot data.
    // Uses last snapshot's remaining_points
    // as the most current remaining value.
    // remaining  = lastSnapshot.remaining_points
    // completed  = total_points - remaining
    // percent    = completed / total_points * 100
    // ==========================================
    calculateMetrics(sprint) {
        if (!sprint) {
            this.state.metrics = { totalPoints: 0, remainingPoints: 0, completedPoints: 0, percentComplete: 0 };
            return;
        }
        const { total_points, snapshots } = sprint;

        // Most recent daily snapshot = last in asc-sorted array
        const lastSnapshot = snapshots && snapshots.length ? snapshots[snapshots.length - 1] : null;
        const remaining = lastSnapshot ? lastSnapshot.remaining_points : total_points;
        const completed = total_points - remaining;
        const percent = total_points > 0 ? Math.round((completed / total_points) * 100) : 0;

        this.state.metrics = {
            totalPoints: total_points || 0,
            remainingPoints: remaining || 0,
            completedPoints: completed || 0,
            percentComplete: percent
        };
    }

    // ==========================================
    // BUILD OR UPDATE — called after sprint selection
    // or initial load. If chart exists: updates data
    // in place with smooth animation ('active' mode).
    // If not: creates it fresh via renderChart().
    // ==========================================
    buildOrUpdateChart(sprint) {
        if (!sprint || !sprint.start_date || !this.canvasRef.el) return;

        try {
            const { start_date, end_date, total_points, snapshots } = sprint;

            // Generate one label per calendar day from start to end
            const labels = this.generateLabels(start_date, end_date);

            // Ideal burndown: perfectly straight line from total_points → 0
            // Divides total points evenly across all days
            const idealLine = labels.map((_, i) =>
                parseFloat((total_points - (i * (total_points / (labels.length - 1 || 1)))).toFixed(2))
            );

            // Actual remaining: maps each date label to its snapshot value.
            // null = no snapshot for that date (cron didn't run / gap in data)
            // Chart.js renders nulls as gaps in the line
            const actualPoints = labels.map(l => {
                const s = snapshots.find(snap => snap.date === l);
                return s !== undefined ? s.remaining_points : null;
            });

            if (this.chartInstance) {
                // Smooth update — no destroy/recreate, just swap data
                this.chartInstance.data.labels = labels;
                this.chartInstance.data.datasets[0].data = idealLine;
                this.chartInstance.data.datasets[1].data = actualPoints;
                this.chartInstance.update('active'); // 'active' = animated transition
            } else {
                // First render
                this.renderChart(labels, idealLine, actualPoints);
            }
        } catch (e) {
            console.error("Burndown: buildOrUpdateChart failed:", e);
            this.state.error = "Chart failed to render.";
        }
    }

    // ==========================================
    // RENDER — creates the Chart.js instance.
    // Only called once on first load.
    // Subsequent sprint changes go through
    // buildOrUpdateChart which updates in place.
    // Dataset order matters:
    //   [0] Ideal line    (dashed purple)
    //   [1] Actual line   (solid blue, stepped, filled)
    // ==========================================
    renderChart(labels, idealLine, actualPoints) {
        if (!this.canvasRef.el) return;
        try {
            const ctx = this.canvasRef.el.getContext("2d");
            this.chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            // [0] Ideal burndown — straight dashed purple line
                            // Shows what perfect progress would look like
                            label: 'Ideal',
                            data: idealLine,
                            borderColor: '#9333ea',
                            borderDash: [5, 5],
                            pointRadius: 0,
                            tension: 0,
                            fill: false
                        },
                        {
                            // [1] Actual remaining — stepped blue line with fill
                            // Steps reflect that work completes in chunks not continuously
                            // Gaps (null values) appear where cron didn't run
                            label: 'Actual Remaining',
                            data: actualPoints,
                            borderColor: '#3b82f6',
                            backgroundColor: 'rgba(59, 130, 246, 0.05)',
                            stepped: true,
                            fill: true,
                            tension: 0
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        duration: 400,
                        easing: 'easeInOutQuart'
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: 'Story Points' }
                        },
                        x: {
                            title: { display: true, text: 'Date' }
                        }
                    }
                }
            });
        } catch (e) {
            console.error("Burndown: Chart.js render failed:", e);
            this.state.error = "Chart failed to render.";
        }
    }

    // ==========================================
    // GENERATE LABELS — produces one date string
    // per calendar day between start and end dates.
    // Format: 'YYYY-MM-DD' (matches snapshot.date from backend)
    // Used for both X axis labels and snapshot lookup by date.
    // ==========================================
    generateLabels(s, e) {
        const dates = [];
        let curr = new Date(s);
        const end = new Date(e);
        while (curr <= end) {
            dates.push(curr.toISOString().split('T')[0]);
            curr.setDate(curr.getDate() + 1);
        }
        return dates;
    }
}

BurndownChart.template = "scrum_management.BurndownChart";
BurndownChart.props = { projectId: { type: Number } };