/** @odoo-module */

import { Component, onMounted, useRef, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class VelocityChart extends Component {
    setup() {
        this.orm = useService("orm");
        this.canvasRef = useRef("chartCanvas");
        this.chartInstance = null;

        // Reactive state:
        // rawData       — full unfiltered dataset from server (all velocity snapshots)
        // filter        — current view filter: 'last_5' | 'last_10' | 'all'
        // rollingWindow — dynamic window size for moving averages, defaults to 3 (standard Agile)
        // metrics       — KPI indicators shown above the chart (avg, last3, best3, worst3)
        this.state = useState({
            rawData: [],
            filter: 'last_10',
            rollingWindow: 3,
            metrics: {
                average: 0,
                last3: 0,
                best3: 0,
                worst3: 0
            }
        });

        onMounted(async () => {
            // Load Chart.js from Odoo's bundled static lib
            await loadJS("/web/static/lib/Chart/Chart.js");
            // Fetch all velocity snapshots for this project in one shot
            await this.fetchRawData();
        });

        onWillUnmount(() => {
            // Destroy Chart.js instance to prevent canvas memory leaks
            if (this.chartInstance) {
                this.chartInstance.destroy();
            }
        });
    }

    // ==========================================
    // FETCH — one server call, all data at once
    // Sorting is done in JS (sprint_id ascending = oldest to newest)
    // ==========================================
    async fetchRawData() {
        if (!this.props.projectId) return;

        try {
            // Calls get_velocity_chart_data on project.velocity.snapshot model
            const data = await this.orm.call(
                "project.velocity.snapshot",
                "get_velocity_chart_data",
                [this.props.projectId]
            );

            // Sort ascending by sprint ID so chart renders left=oldest, right=newest
            let sortedData = (data || []).sort((a, b) => {
                return a.sprint_id[0] - b.sprint_id[0];
            });

            this.state.rawData = sortedData;

            // Only render if we have data
            if (this.state.rawData.length > 0) {
                this.buildOrUpdateChart();
            }
        } catch (error) {
            console.error("Failed to load Velocity Chart Data:", error);
        }
    }

    // ==========================================
    // FILTER — called by Last 5 / Last 10 / All Time buttons
    // No server call — just slices rawData in JS
    // ==========================================
    setFilter(newFilter) {
        this.state.filter = newFilter;
        this.buildOrUpdateChart();
    }

    // Method to handle rolling window changes
    setRollingWindow(size) {
        this.state.rollingWindow = size;
        this.buildOrUpdateChart();
    }

    // ==========================================
    // METRICS — calculates KPI indicators from
    // the currently filtered (visible) data only
    // ==========================================
    calculateMetrics(filteredData) {
        // Extract delivered velocities as plain numbers
        const delivered = filteredData.map(d => d.delivered_velocity).filter(v => typeof v === 'number');

        if (delivered.length === 0) {
            this.state.metrics = { average: 0, last3: 0, best3: 0, worst3: 0 };
            return;
        }

        const sum = arr => arr.reduce((a, b) => a + b, 0);
        const avg = arr => arr.length ? (sum(arr) / arr.length).toFixed(2) : 0;

        // Overall average of all visible sprints
        const average = avg(delivered);

        // Average of the 3 most recent sprints
        const last3 = avg(delivered.slice(-3));

        // Average of the 3 highest-delivering sprints
        const sortedDesc = [...delivered].sort((a, b) => b - a);
        const best3 = avg(sortedDesc.slice(0, 3));

        // Average of the 3 lowest-delivering sprints
        const sortedAsc = [...delivered].sort((a, b) => a - b);
        const worst3 = avg(sortedAsc.slice(0, 3));

        this.state.metrics = {
            average: parseFloat(average),
            last3: parseFloat(last3),
            best3: parseFloat(best3),
            worst3: parseFloat(worst3)
        };
    }

    // ==========================================
    // BUILD OR UPDATE — called on filter change
    // or after initial data fetch.
    // If chart exists: updates data smoothly.
    // If not: creates it fresh via renderChart().
    // ==========================================
    buildOrUpdateChart() {
        // Apply the active filter by slicing rawData
        let filteredData = [...this.state.rawData];
        if (this.state.filter === 'last_5') {
            filteredData = filteredData.slice(-5);
        } else if (this.state.filter === 'last_10') {
            filteredData = filteredData.slice(-10);
        }

        // Recalculate KPI metrics for the visible data
        this.calculateMetrics(filteredData);

        // Calculate both planned and delivered rolling averages dynamically in JS.
        // Uses the selected rollingWindow size to determine the sliding window offset.
        const windowOffset = this.state.rollingWindow - 1;

        const plannedRolling = filteredData.map((_, i) => {
            const windowData = filteredData.slice(Math.max(0, i - windowOffset), i + 1);
            const avgVal = windowData.reduce((sum, d) => sum + d.planned_velocity, 0) / windowData.length;
            return parseFloat(avgVal.toFixed(2));
        });

        const deliveredRolling = filteredData.map((_, i) => {
            const windowData = filteredData.slice(Math.max(0, i - windowOffset), i + 1);
            const avgVal = windowData.reduce((sum, d) => sum + d.delivered_velocity, 0) / windowData.length;
            return parseFloat(avgVal.toFixed(2));
        });

        // Assemble chart data arrays
        const chartData = {
            labels: filteredData.map(d => d.sprint_id[1]),         // Sprint names for X axis
            trend: deliveredRolling,                                // Dynamically calculated delivered rolling
            plannedRolling: plannedRolling,                          // Dynamically calculated planned rolling
            planned: filteredData.map(d => d.planned_velocity),     // Raw planned bars
            delivered: filteredData.map(d => d.delivered_velocity)   // Raw delivered bars
        };

        if (this.chartInstance) {
            // Chart already exists — update data in place for smooth transition
            this.chartInstance.data.labels = chartData.labels;
            this.chartInstance.data.datasets[0].data = chartData.trend;
            this.chartInstance.data.datasets[0].label = `Rolling Avg (Delivered: ${this.state.rollingWindow})`;
            this.chartInstance.data.datasets[1].data = chartData.plannedRolling;
            this.chartInstance.data.datasets[1].label = `Rolling Avg (Planned: ${this.state.rollingWindow})`;
            this.chartInstance.data.datasets[2].data = chartData.planned;
            this.chartInstance.data.datasets[3].data = chartData.delivered;
            this.chartInstance.update();
        } else {
            // First render — create the Chart.js instance
            this.renderChart(chartData);
        }
    }

    // ==========================================
    // RENDER — creates the Chart.js instance.
    // Only called once (first load).
    // Subsequent updates go through buildOrUpdateChart.
    // Dataset order matters — must match index references above:
    //   [0] Rolling Avg Delivered (line)
    //   [1] Rolling Avg Planned   (dashed line)
    //   [2] Planned               (bar)
    //   [3] Delivered             (bar)
    // ==========================================
    renderChart(chartData) {
        const ctx = this.canvasRef.el.getContext('2d');

        this.chartInstance = new Chart(ctx, {
            type: 'bar', // default type; datasets override with 'line' where needed
            data: {
                labels: chartData.labels,
                datasets: [
                    {
                        // [0] Delivered rolling average — solid purple line
                        type: 'line',
                        label: `Rolling Avg (Delivered: ${this.state.rollingWindow})`,
                        data: chartData.trend,
                        borderColor: '#8b5cf6',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3
                    },
                    {
                        // [1] Planned rolling average — dashed amber line
                        type: 'line',
                        label: `Rolling Avg (Planned: ${this.state.rollingWindow})`,
                        data: chartData.plannedRolling,
                        borderColor: '#f59e0b',
                        borderDash: [5, 5],
                        borderWidth: 2,
                        fill: false,
                        tension: 0.3,
                        pointRadius: 3
                    },
                    {
                        // [2] Planned story points — grey bars
                        label: 'Planned',
                        data: chartData.planned,
                        backgroundColor: '#cbd5e1',
                        borderRadius: 4
                    },
                    {
                        // [3] Delivered story points — blue bars
                        label: 'Delivered',
                        data: chartData.delivered,
                        backgroundColor: '#3b82f6',
                        borderRadius: 4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }
}

VelocityChart.template = "scrum_management.VelocityChart";
VelocityChart.xml = "scrum_management/static/src/xml/velocity_chart.xml";
VelocityChart.props = { projectId: { type: Number } };