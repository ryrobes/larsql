import React, { useMemo } from 'react';
import { Icon } from '@iconify/react';
import './EvolutionMetrics.css';

/**
 * MetricCard - Compact metric display
 */
function MetricCard({ icon, label, value, subvalue, trend, color }) {
  return (
    <div className="metric-card">
      <div className="metric-icon" style={{ color }}>
        <Icon icon={icon} width="16" />
      </div>
      <div className="metric-content">
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        {subvalue && <div className="metric-subvalue">{subvalue}</div>}
        {trend && (
          <div className={`metric-trend ${trend.direction}`}>
            <Icon icon={trend.direction === 'up' ? 'mdi:trending-up' : 'mdi:trending-down'} width="12" />
            {trend.value}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * EvolutionMetrics - Compact dashboard showing key evolution stats
 *
 * Props:
 * - nodes: Evolution nodes array
 * - metadata: Evolution metadata
 */
const EvolutionMetrics = ({ nodes, metadata }) => {
  const metrics = useMemo(() => {
    if (!nodes || nodes.length === 0) {
      return null;
    }

    // Group by generation
    const generations = {};
    nodes.forEach(node => {
      const gen = node.data.generation;
      if (!generations[gen]) {
        generations[gen] = {
          candidates: [],
          winner: null,
          totalCost: 0,
        };
      }
      generations[gen].candidates.push(node.data);
      generations[gen].totalCost += node.data.cost || 0;
      if (node.data.is_winner) {
        generations[gen].winner = node.data;
      }
    });

    const genArray = Object.values(generations).sort((a, b) => a.candidates[0].generation - b.candidates[0].generation);
    const totalGenerations = genArray.length;

    // Total cost
    const totalCost = nodes.reduce((sum, n) => sum + (n.data.cost || 0), 0);

    // Average cost per generation
    const avgCostPerGen = totalCost / totalGenerations;

    // Cost trend (first half vs second half)
    const midpoint = Math.floor(totalGenerations / 2);
    const firstHalfCost = genArray.slice(0, midpoint).reduce((sum, g) => sum + g.totalCost, 0) / midpoint;
    const secondHalfCost = genArray.slice(midpoint).reduce((sum, g) => sum + g.totalCost, 0) / (totalGenerations - midpoint);
    const costChange = ((secondHalfCost - firstHalfCost) / firstHalfCost * 100);

    // Gene pool size (active training set)
    const genePoolSize = Math.min(5, totalGenerations);

    // Model diversity
    const uniqueModels = new Set(nodes.map(n => n.data.model).filter(Boolean)).size;

    // Mutation usage
    const mutatedCount = nodes.filter(n => n.data.mutation_type && n.data.mutation_type !== 'nan').length;
    const mutationPct = (mutatedCount / nodes.length * 100);

    // Winners with mutations
    const winners = nodes.filter(n => n.data.is_winner);
    const mutatedWinners = winners.filter(w => w.data.mutation_type && w.data.mutation_type !== 'nan');
    const mutatedWinnerPct = winners.length > 0 ? (mutatedWinners.length / winners.length * 100) : 0;

    // Training set members (marked as in_training_set)
    const trainingSetSize = nodes.filter(n => n.data.in_training_set).length;

    // Average candidates per generation
    const avgCandidatesPerGen = nodes.length / totalGenerations;

    // Best generation (lowest cost with winner)
    const bestGen = genArray.reduce((best, g) => {
      if (g.winner && (!best || g.totalCost < best.totalCost)) {
        return g;
      }
      return best;
    }, null);

    return {
      totalGenerations,
      totalCost,
      avgCostPerGen,
      costTrend: {
        direction: costChange < 0 ? 'down' : 'up',
        value: `${Math.abs(costChange).toFixed(0)}%`
      },
      genePoolSize,
      trainingSetSize,
      uniqueModels,
      mutationPct,
      mutatedWinnerPct,
      avgCandidatesPerGen,
      bestGeneration: bestGen?.candidates[0]?.generation,
      bestGenCost: bestGen?.totalCost,
    };
  }, [nodes]);

  if (!metrics) {
    return null;
  }

  return (
    <div className="evolution-metrics">
      <MetricCard
        icon="mdi:counter"
        label="Generations"
        value={metrics.totalGenerations}
        subvalue={`${metrics.avgCandidatesPerGen.toFixed(1)} avg candidates`}
        color="#00e5ff"
      />
      <MetricCard
        icon="mdi:currency-usd"
        label="Total Cost"
        value={`$${metrics.totalCost.toFixed(4)}`}
        subvalue={`$${metrics.avgCostPerGen.toFixed(5)} per gen`}
        trend={metrics.costTrend}
        color="#34d399"
      />
      <MetricCard
        icon="mdi:trophy"
        label="Best Gen"
        value={`Gen ${metrics.bestGeneration}`}
        subvalue={`$${metrics.bestGenCost?.toFixed(5)}`}
        color="#fbbf24"
      />
      <MetricCard
        icon="mdi:dna"
        label="Gene Pool"
        value={metrics.genePoolSize}
        subvalue={`${metrics.trainingSetSize} in training`}
        color="#9333ea"
      />
      <MetricCard
        icon="mdi:robot"
        label="Models"
        value={metrics.uniqueModels}
        subvalue={metrics.uniqueModels === 1 ? 'Single model' : 'Multi-model'}
        color="#06b6d4"
      />
      <MetricCard
        icon="mdi:auto-fix"
        label="Mutations"
        value={`${metrics.mutationPct.toFixed(0)}%`}
        subvalue={`${metrics.mutatedWinnerPct.toFixed(0)}% of winners`}
        color="#f59e0b"
      />
    </div>
  );
};

export default EvolutionMetrics;
