import React, { useState, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';

/**
 * ArtifactsPalette - Draggable Rabbitize artifacts for Jinja templates
 *
 * Displays artifacts from browser automation phases:
 * - images (screenshots)
 * - dom_snapshots
 * - video
 *
 * Draggable as: {{ phase_name.images.0 }}
 */

// Artifact type metadata
const ARTIFACT_TYPES = {
  images: { icon: 'mdi:image-multiple', color: '#a78bfa', label: 'Screenshots' },
  dom_snapshots: { icon: 'mdi:code-tags', color: '#60a5fa', label: 'DOM Snapshots' },
  dom_coords: { icon: 'mdi:crosshairs-gps', color: '#34d399', label: 'DOM Coords' },
  video: { icon: 'mdi:video', color: '#f87171', label: 'Video' },
};

/**
 * Draggable artifact pill
 */
function ArtifactPill({ phaseName, artifactType, index, label }) {
  const config = ARTIFACT_TYPES[artifactType] || ARTIFACT_TYPES.images;

  // Build Jinja path
  const jinjaPath = index !== null
    ? `${phaseName}.${artifactType}.${index}`
    : `${phaseName}.${artifactType}`;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `artifact-${phaseName}-${artifactType}-${index}`,
    data: { type: 'variable', variablePath: jinjaPath },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={`var-pill ${isDragging ? 'dragging' : ''}`}
      style={{ borderColor: config.color + '34' }}
      title={`{{ ${jinjaPath} }}`}
    >
      <Icon icon={config.icon} width="12" style={{ color: config.color }} />
      <span style={{ color: config.color }}>{label}</span>
    </div>
  );
}

/**
 * Artifact type group (images, dom_snapshots, etc.)
 */
function ArtifactTypeGroup({ phaseName, artifactType, count, defaultOpen = false }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);
  const config = ARTIFACT_TYPES[artifactType] || ARTIFACT_TYPES.images;

  if (count === 0) return null;

  // For single items (like video), show directly
  const isSingleItem = artifactType === 'video';

  if (isSingleItem) {
    return (
      <ArtifactPill
        phaseName={phaseName}
        artifactType={artifactType}
        index={null}
        label={config.label}
      />
    );
  }

  // For collections (images, dom_snapshots), show expandable group
  return (
    <div className="var-group" style={{ marginLeft: '12px' }}>
      <div
        className="var-group-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="var-group-chevron"
        />
        <Icon icon={config.icon} width="12" className="var-group-icon" />
        <span className="var-group-title">{config.label}</span>
        <span className="var-group-count">{count}</span>
      </div>

      {isExpanded && (
        <div className="var-group-content">
          {Array.from({ length: count }).map((_, idx) => (
            <ArtifactPill
              key={idx}
              phaseName={phaseName}
              artifactType={artifactType}
              index={idx}
              label={`${idx}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Phase artifact group
 */
function PhaseArtifactsGroup({ phaseName, artifacts, defaultOpen = true }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);

  const totalCount = Object.values(artifacts).reduce((sum, count) => sum + count, 0);

  return (
    <div className="var-group">
      <div
        className="var-group-header"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <Icon
          icon={isExpanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width="12"
          className="var-group-chevron"
        />
        <Icon icon="mdi:record-circle" width="12" className="var-group-icon" style={{ color: '#f87171' }} />
        <span className="var-group-title">{phaseName}</span>
        <span className="var-group-count">{totalCount}</span>
      </div>

      {isExpanded && (
        <div className="artifact-types-list">
          {Object.entries(artifacts).map(([type, count]) => (
            <ArtifactTypeGroup
              key={type}
              phaseName={phaseName}
              artifactType={type}
              count={count}
              defaultOpen={false}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Main ArtifactsPalette component
 */
function ArtifactsPalette() {
  const { cascade, cellStates } = useStudioCascadeStore();

  // Introspect cascade for rabbitize phases with artifacts
  const phaseArtifacts = useMemo(() => {
    const artifacts = {};

    if (!cascade?.phases) return artifacts;

    cascade.phases.forEach(phase => {
      // Check if this is a rabbitize phase (linux_shell with rabbitize command)
      const isRabbitize = phase.tool === 'linux_shell' &&
                          phase.inputs?.command?.includes('rabbitize');

      if (!isRabbitize) return;

      const cellState = cellStates[phase.name];
      const phaseArtifacts = {};

      // Strategy 1: If phase has been run successfully, get artifacts from result
      if (cellState?.status === 'success') {
        // Images (screenshots)
        if (cellState.images && Array.isArray(cellState.images)) {
          phaseArtifacts.images = cellState.images.length;
        }

        // Check result for artifact metadata (when backend provides it)
        const result = cellState.result;
        if (result && typeof result === 'object') {
          if (result.screenshots) {
            phaseArtifacts.images = Array.isArray(result.screenshots)
              ? result.screenshots.length
              : result.screenshots;
          }
          if (result.dom_snapshots) {
            phaseArtifacts.dom_snapshots = Array.isArray(result.dom_snapshots)
              ? result.dom_snapshots.length
              : result.dom_snapshots;
          }
          if (result.video || result.has_video) {
            phaseArtifacts.video = 1;
          }
        }
      }

      // Strategy 2: If phase hasn't run yet, infer artifacts from batch commands
      // This handles the recording session case where artifacts exist but phase hasn't executed
      if (Object.keys(phaseArtifacts).length === 0) {
        const command = phase.inputs?.command || '';

        // Parse batch commands to estimate artifacts
        const batchMatch = command.match(/--batch-commands='(\[[\s\S]*?\])'/);
        if (batchMatch) {
          try {
            const commands = JSON.parse(batchMatch[1]);

            // Rabbitize captures one of each artifact at each step (except :wait)
            const artifactSteps = commands.filter(cmd => {
              const cmdType = Array.isArray(cmd) ? cmd[0] : cmd;
              return cmdType !== ':wait';
            }).length;

            if (artifactSteps > 0) {
              // Each step generates all three artifact types
              phaseArtifacts.images = artifactSteps;
              phaseArtifacts.dom_snapshots = artifactSteps;
              phaseArtifacts.dom_coords = artifactSteps;
            }

            // Video: Check if video recording is enabled
            if (command.includes('--process-video')) {
              phaseArtifacts.video = 1;
            }
          } catch (e) {
            console.error('Failed to parse batch commands for artifacts:', e);
          }
        }
      }

      // Only add phase if it has artifacts
      if (Object.keys(phaseArtifacts).length > 0) {
        artifacts[phase.name] = phaseArtifacts;
      }
    });

    return artifacts;
  }, [cascade, cellStates]);

  const hasArtifacts = Object.keys(phaseArtifacts).length > 0;

  if (!hasArtifacts) return null;

  return (
    <div className="var-palette">
      <div className="var-palette-header">
        <Icon icon="mdi:folder-image" width="16" />
        <span>Artifacts</span>
      </div>

      <div className="var-palette-content">
        {Object.entries(phaseArtifacts).map(([phaseName, artifacts]) => (
          <PhaseArtifactsGroup
            key={phaseName}
            phaseName={phaseName}
            artifacts={artifacts}
            defaultOpen={Object.keys(phaseArtifacts).length === 1}
          />
        ))}
      </div>

      <div className="var-palette-hint">
        Drag artifacts into code to insert Jinja template
      </div>
    </div>
  );
}

export default ArtifactsPalette;
