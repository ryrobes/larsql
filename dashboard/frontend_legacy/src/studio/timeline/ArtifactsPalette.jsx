import React, { useState, useMemo } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { Icon } from '@iconify/react';
import useStudioCascadeStore from '../stores/studioCascadeStore';

/**
 * ArtifactsPalette - Draggable Rabbitize artifacts for Jinja templates
 *
 * Displays artifacts from browser automation cells:
 * - images (screenshots)
 * - dom_snapshots
 * - video
 *
 * Draggable as: {{ cell_name.images.0 }}
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
function ArtifactPill({ cellName, artifactType, index, label }) {
  const config = ARTIFACT_TYPES[artifactType] || ARTIFACT_TYPES.images;

  // Build Jinja path - artifacts are accessed via outputs.cell_name.artifact_type[index]
  // NOTE: Jinja requires bracket notation for numeric indices
  const jinjaPath = index !== null
    ? `outputs.${cellName}.${artifactType}[${index}]`
    : `outputs.${cellName}.${artifactType}`;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `artifact-${cellName}-${artifactType}-${index}`,
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
function ArtifactTypeGroup({ cellName, artifactType, count, defaultOpen = false }) {
  const [isExpanded, setIsExpanded] = useState(defaultOpen);
  const config = ARTIFACT_TYPES[artifactType] || ARTIFACT_TYPES.images;

  if (count === 0) return null;

  // For single items (like video), show directly
  const isSingleItem = artifactType === 'video';

  if (isSingleItem) {
    return (
      <ArtifactPill
        cellName={cellName}
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
              cellName={cellName}
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
 * Cell artifact group
 */
function CellArtifactsGroup({ cellName, artifacts, defaultOpen = true }) {
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
        <span className="var-group-title">{cellName}</span>
        <span className="var-group-count">{totalCount}</span>
      </div>

      {isExpanded && (
        <div className="artifact-types-list">
          {Object.entries(artifacts).map(([type, count]) => (
            <ArtifactTypeGroup
              key={type}
              cellName={cellName}
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

  // Introspect cascade for rabbitize cells with artifacts
  const cellArtifacts = useMemo(() => {
    const artifacts = {};

    if (!cascade?.cells) return artifacts;

    cascade.cells.forEach(cell => {
      // Check if this is a rabbitize cell (linux_shell with rabbitize command)
      const isRabbitize = cell.tool === 'linux_shell' &&
                          cell.inputs?.command?.includes('rabbitize');

      if (!isRabbitize) return;

      const cellState = cellStates[cell.name];
      const cellArtifacts = {};

      // Strategy 1: If cell has been run successfully, get artifacts from result
      if (cellState?.status === 'success') {
        // Images (screenshots)
        if (cellState.images && Array.isArray(cellState.images)) {
          cellArtifacts.images = cellState.images.length;
        }

        // Check result for artifact metadata (when backend provides it)
        const result = cellState.result;
        if (result && typeof result === 'object') {
          if (result.screenshots) {
            cellArtifacts.images = Array.isArray(result.screenshots)
              ? result.screenshots.length
              : result.screenshots;
          }
          if (result.dom_snapshots) {
            cellArtifacts.dom_snapshots = Array.isArray(result.dom_snapshots)
              ? result.dom_snapshots.length
              : result.dom_snapshots;
          }
          if (result.video || result.has_video) {
            cellArtifacts.video = 1;
          }
        }
      }

      // Strategy 2: If cell hasn't run yet, infer artifacts from batch commands
      // This handles the recording session case where artifacts exist but cell hasn't executed
      if (Object.keys(cellArtifacts).length === 0) {
        const command = cell.inputs?.command || '';

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
              cellArtifacts.images = artifactSteps;
              cellArtifacts.dom_snapshots = artifactSteps;
              cellArtifacts.dom_coords = artifactSteps;
            }

            // Video: Check if video recording is enabled
            if (command.includes('--process-video')) {
              cellArtifacts.video = 1;
            }
          } catch (e) {
            console.error('Failed to parse batch commands for artifacts:', e);
          }
        }
      }

      // Only add cell if it has artifacts
      if (Object.keys(cellArtifacts).length > 0) {
        artifacts[cell.name] = cellArtifacts;
      }
    });

    return artifacts;
  }, [cascade, cellStates]);

  const hasArtifacts = Object.keys(cellArtifacts).length > 0;

  if (!hasArtifacts) return null;

  return (
    <div className="var-palette">
      <div className="var-palette-header">
        <Icon icon="mdi:folder-image" width="16" />
        <span>Artifacts</span>
      </div>

      <div className="var-palette-content">
        {Object.entries(cellArtifacts).map(([cellName, artifacts]) => (
          <CellArtifactsGroup
            key={cellName}
            cellName={cellName}
            artifacts={artifacts}
            defaultOpen={Object.keys(cellArtifacts).length === 1}
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
