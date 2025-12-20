import React, { useCallback, memo } from 'react';
import { Handle, Position } from 'reactflow';
import { Icon } from '@iconify/react';
import usePlaygroundStore from '../../stores/playgroundStore';
import './PromptNode.css';

/**
 * PromptNode - Text input node for prompts
 *
 * Has a source handle (right) to connect to generators.
 */
function PromptNode({ id, data, selected }) {
  const updateNodeData = usePlaygroundStore(state => state.updateNodeData);

  const handleTextChange = useCallback((e) => {
    updateNodeData(id, { text: e.target.value });
  }, [id, updateNodeData]);

  return (
    <div className={`prompt-node ${selected ? 'selected' : ''}`}>
      <div className="prompt-node-header">
        <div className="prompt-node-icon">
          <Icon icon="mdi:text-box" width="16" />
        </div>
        <span className="prompt-node-title">Prompt</span>
      </div>

      <div className="prompt-node-body">
        <textarea
          className="prompt-textarea"
          value={data.text || ''}
          onChange={handleTextChange}
          placeholder="Enter your prompt..."
          rows={3}
        />
      </div>

      {/* Source handle for connecting to generators */}
      <Handle
        type="source"
        position={Position.Right}
        id="output"
        className="prompt-handle"
      />
    </div>
  );
}

export default memo(PromptNode);
