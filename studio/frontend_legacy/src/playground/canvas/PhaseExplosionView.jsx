import React, { useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '@iconify/react';
import RichMarkdown from '../../components/RichMarkdown';
import './CellExplosionView.css';

/**
 * CellExplosionView - Fullscreen 3D explosion of soundings/reforge cards
 *
 * Animates cards from their canvas origin position toward the user,
 * then spreads them out spatially to show the full decision tree.
 *
 * Uses CSS 3D transforms for skeuomorphic "lifting" effect.
 */
function CellExplosionView({ cellData, originRect, onClose }) {
  const [animationCell, setAnimationCell] = useState('lifting'); // lifting → spreading → settled
  const containerRef = useRef(null);

  // Extract data
  const {
    name,
    soundingsProgress = [],
    soundingsOutputs = {},
    reforgeOutputs = {},
    winnerIndex = null,
    currentReforgeStep = 0,
    totalReforgeSteps = 0,
    evaluatorReasoning = '',
    aggregatorReasoning = '',
    parsedCell = {},
  } = cellData;

  const soundingsFactor = soundingsProgress.length;
  const hasReforge = totalReforgeSteps > 0 && Object.keys(reforgeOutputs).length > 0;
  const isAggregate = parsedCell?.soundings?.mode === 'aggregate';

  // Debug logging
  console.log('[CellExplosion] Data:', {
    name,
    soundingsFactor,
    soundingsProgress,
    soundingsOutputs,
    hasReforge,
    totalReforgeSteps,
    reforgeOutputs,
    currentReforgeStep,
    winnerIndex,
    evaluatorReasoning,
    liveLog: cellData.liveLog
  });

  // Debug reforge specifically
  if (totalReforgeSteps > 0) {
    console.log('[CellExplosion] REFORGE DEBUG:', {
      totalReforgeSteps,
      currentReforgeStep,
      reforgeOutputsKeys: Object.keys(reforgeOutputs),
      reforgeOutputsValues: reforgeOutputs,
      hasReforge,
    });
  }

  // Animation sequence
  useEffect(() => {
    // Cell 1: Lifting (0-500ms)
    const liftTimer = setTimeout(() => setAnimationCell('spreading'), 500);
    // Cell 2: Spreading (500-1200ms)
    const spreadTimer = setTimeout(() => setAnimationCell('settled'), 1200);

    return () => {
      clearTimeout(liftTimer);
      clearTimeout(spreadTimer);
    };
  }, []);

  // Keyboard handling
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Compute card positions with dynamic sizing
  const computeLayout = () => {
    const CARD_GAP = 24;
    const STEP_GAP = 100;
    const MIN_CARD_WIDTH = 320;
    const MAX_CARD_WIDTH = 600;
    const MIN_CARD_HEIGHT = 400;
    const MAX_CARD_HEIGHT = 700;

    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Dynamic card sizing based on count and screen space
    const soundingsCount = soundingsFactor;
    const availableWidth = viewportWidth - 80; // Leave margins
    const availableHeight = viewportHeight - 200; // Leave space for header/footer

    // Calculate optimal card width based on count
    let CARD_WIDTH = MIN_CARD_WIDTH;
    if (soundingsCount > 0) {
      const totalGaps = (soundingsCount - 1) * CARD_GAP;
      const calculatedWidth = (availableWidth - totalGaps) / soundingsCount;
      CARD_WIDTH = Math.max(MIN_CARD_WIDTH, Math.min(MAX_CARD_WIDTH, calculatedWidth));
    }

    // Calculate card height (taller for more reading space)
    const CARD_HEIGHT = Math.max(MIN_CARD_HEIGHT, Math.min(MAX_CARD_HEIGHT, availableHeight * 0.6));

    // Soundings: horizontal spread near top
    const soundingsWidth = (CARD_WIDTH * soundingsCount) + (CARD_GAP * (soundingsCount - 1));
    const soundingsStartX = Math.max(40, (viewportWidth - soundingsWidth) / 2);
    const soundingsY = 120;

    const soundingsLayout = soundingsProgress.map((s, i) => {
      const output = soundingsOutputs[i];
      console.log(`[Layout] Sounding ${i}:`, { progress: s, output, type: typeof output });
      return {
        index: i,
        x: soundingsStartX + (i * (CARD_WIDTH + CARD_GAP)),
        y: soundingsY,
        width: CARD_WIDTH,
        height: CARD_HEIGHT,
        data: s,
        output,
        isWinner: winnerIndex === i,
        isEliminated: winnerIndex !== null && winnerIndex !== i,
      };
    });

    // Reforge steps: vertical chain below winner
    const reforgeStepsLayout = [];
    if (hasReforge && totalReforgeSteps > 0) {
      // Position below soundings + evaluator reasoning section
      let currentY = soundingsY + CARD_HEIGHT + STEP_GAP + 120; // Extra space for reasoning

      console.log('[Layout] Reforge:', { totalReforgeSteps, currentReforgeStep, reforgeOutputs, startY: currentY });

      for (let step = 1; step <= totalReforgeSteps; step++) {
        const output = reforgeOutputs[step];
        const isCurrentStep = step === currentReforgeStep;
        const isComplete = step <= currentReforgeStep;

        console.log(`[Layout] Reforge step ${step}:`, {
          output: output ? `${output.substring(0, 50)}...` : 'none',
          type: typeof output,
          isCurrentStep,
          isComplete,
          position: { x: (viewportWidth - CARD_WIDTH) / 2, y: currentY }
        });

        reforgeStepsLayout.push({
          step,
          x: (viewportWidth - CARD_WIDTH) / 2,
          y: currentY,
          width: CARD_WIDTH,
          height: CARD_HEIGHT,
          output,
          isCurrentStep,
          isComplete,
        });

        currentY += CARD_HEIGHT + STEP_GAP;
      }

      console.log('[Layout] Total reforge cards to render:', reforgeStepsLayout.length);
    } else {
      console.log('[Layout] No reforge cards:', { hasReforge, totalReforgeSteps, reforgeOutputsCount: Object.keys(reforgeOutputs).length });
    }

    return { soundings: soundingsLayout, reforgeSteps: reforgeStepsLayout };
  };

  const layout = computeLayout();

  // Origin point for animation
  const originX = originRect.left + originRect.width / 2;
  const originY = originRect.top + originRect.height / 2;

  // Calculate total height needed for all cards
  const totalHeight = layout.candidates.length > 0
    ? layout.candidates[0].y + layout.candidates[0].height +
      (layout.reforgeSteps.length > 0
        ? layout.reforgeSteps[layout.reforgeSteps.length - 1].y +
          layout.reforgeSteps[layout.reforgeSteps.length - 1].height -
          layout.candidates[0].y + 200 // Extra padding at bottom
        : 200)
    : 800;

  return createPortal(
    <div
      className={`cell-explosion-overlay cell-${animationCell}`}
      onClick={onClose}
      ref={containerRef}
    >
      {/* Content container with proper height for all cards */}
      <div className="explosion-content" style={{ minHeight: totalHeight }}>
        {/* Minimal floating controls */}
        <div className="explosion-header" onClick={(e) => e.stopPropagation()}>
          <button className="explosion-back" onClick={onClose} title="Close (ESC)">
            <Icon icon="mdi:arrow-left" width="16" />
            <span>{name}</span>
          </button>
          <button className="explosion-close" onClick={onClose} title="Close">
            <Icon icon="mdi:close" width="18" />
          </button>
        </div>

      {/* Soundings Section - label only, cards rendered directly in overlay */}
      {layout.candidates.length > 0 && (
        <>
          <div className="section-label" style={{ position: 'absolute', left: 40, top: layout.candidates[0].y - 30 }}>
            SOUNDINGS {isAggregate ? '→ FUSION' : `(${soundingsFactor} attempts)`}
          </div>
          {layout.candidates.map((card, i) => (
            <SoundingCard
              key={`sounding-${i}`}
              card={card}
              originX={originX}
              originY={originY}
              animationCell={animationCell}
              delay={i * 100}
            />
          ))}
        </>
      )}

      {/* Evaluator Reasoning - positioned absolutely */}
      {(evaluatorReasoning || aggregatorReasoning) && layout.candidates.length > 0 && (
        <div
          className="explosion-reasoning-inline"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            left: '50%',
            transform: 'translateX(-50%)',
            top: layout.candidates[0].y + layout.candidates[0].height + 40,
            maxWidth: 900,
            width: 'calc(100% - 80px)'
          }}
        >
          <div className="reasoning-inline-box">
            <div className="reasoning-icon">
              <Icon icon={isAggregate ? "mdi:merge" : "mdi:scale-balance"} width="18" />
            </div>
            <div className="reasoning-text">
              <strong>{isAggregate ? 'Aggregator' : 'Evaluator'}:</strong>{' '}
              {evaluatorReasoning || aggregatorReasoning}
            </div>
          </div>
        </div>
      )}

      {/* Reforge Steps - rendered directly in overlay */}
      {layout.reforgeSteps.length > 0 && (
        <>
          <div className="section-label" style={{ position: 'absolute', left: 40, top: layout.reforgeSteps[0].y - 30 }}>
            REFORGE ({layout.reforgeSteps.length} step{layout.reforgeSteps.length > 1 ? 's' : ''})
          </div>
          {layout.reforgeSteps.map((card, i) => {
            console.log(`[Render] Reforge card ${i} at position:`, { x: card.x, y: card.y });
            return (
              <ReforgeCard
                key={`reforge-${i}`}
                card={card}
                originX={originX}
                originY={originY}
                animationCell={animationCell}
                delay={600 + i * 150}
              />
            );
          })}
        </>
      )}
      </div>
    </div>,
    document.body
  );
}

/**
 * Individual sounding card with animation
 */
function SoundingCard({ card, originX, originY, animationCell, delay }) {
  const { index, x, y, width, height, data, output, isWinner, isEliminated } = card;

  // Animation styles
  const getTransform = () => {
    if (animationCell === 'lifting') {
      return {
        transform: `translate(${originX - x - width/2}px, ${originY - y - height/2}px) scale(0.3) translateZ(0px)`,
        opacity: 0,
      };
    }
    if (animationCell === 'spreading') {
      return {
        transform: `translate(0, 0) scale(1) translateZ(100px)`,
        opacity: 1,
      };
    }
    return {
      transform: `translate(0, 0) scale(1) translateZ(0px)`,
      opacity: 1,
    };
  };

  const cardClasses = [
    'explosion-card',
    'sounding-card',
    isWinner ? 'winner' : '',
    isEliminated ? 'eliminated' : '',
    data?.status === 'running' ? 'running' : '',
    data?.status === 'complete' ? 'complete' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={cardClasses}
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width,
        height,
        transition: `all 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) ${delay}ms`,
        ...getTransform(),
      }}
    >
      <div className="explosion-card-header">
        {isWinner && <Icon icon="mdi:trophy" width="16" className="winner-icon" />}
        <span className="card-label">S{index}</span>
        {data?.status && (
          <span className={`card-status status-${data.status}`}>
            {data.status === 'running' && <Icon icon="mdi:loading" width="12" className="spinning" />}
            {data.status === 'complete' && <Icon icon="mdi:check" width="12" />}
            {data.status === 'error' && <Icon icon="mdi:alert-circle" width="12" />}
          </span>
        )}
      </div>

      <div className="explosion-card-content">
        {output && output !== 'undefined' && typeof output !== 'undefined' ? (
          typeof output === 'string' ? (
            <RichMarkdown>{String(output)}</RichMarkdown>
          ) : (
            <pre>{JSON.stringify(output, null, 2).slice(0, 500)}</pre>
          )
        ) : (
          <div className="card-placeholder">
            {data?.status === 'pending' ? 'Pending...' :
             data?.status === 'running' ? 'Running...' :
             data?.status === 'complete' ? 'Complete (no content captured)' :
             'No output'}
          </div>
        )}
      </div>

      {/* Show eliminated badge in corner instead of overlay */}
      {isEliminated && (
        <div className="eliminated-badge">
          <Icon icon="mdi:close-circle" width="16" />
        </div>
      )}
    </div>
  );
}

/**
 * Reforge step card with animation
 */
function ReforgeCard({ card, originX, originY, animationCell, delay }) {
  const { step, x, y, width, height, output, isCurrentStep, isComplete } = card;

  const getTransform = () => {
    if (animationCell === 'lifting') {
      return {
        transform: `translate(${originX - x - width/2}px, ${originY - y - height/2}px) scale(0.3) translateZ(0px)`,
        opacity: 0,
      };
    }
    if (animationCell === 'spreading') {
      return {
        transform: `translate(0, 0) scale(1) translateZ(100px)`,
        opacity: 1,
      };
    }
    return {
      transform: `translate(0, 0) scale(1) translateZ(0px)`,
      opacity: 1,
    };
  };

  const cardClasses = [
    'explosion-card',
    'reforge-card',
    isCurrentStep ? 'current' : '',
    isComplete ? 'complete' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={cardClasses}
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width,
        height,
        transition: `all 0.7s cubic-bezier(0.34, 1.56, 0.64, 1) ${delay}ms`,
        ...getTransform(),
      }}
    >
      <div className="explosion-card-header reforge-header">
        <Icon icon="mdi:auto-fix" width="16" />
        <span className="card-label">R{step}</span>
        {isComplete && <Icon icon="mdi:check-circle" width="14" className="complete-icon" />}
      </div>

      <div className="explosion-card-content">
        {output && output !== 'undefined' && typeof output !== 'undefined' ? (
          typeof output === 'string' ? (
            <RichMarkdown>{String(output)}</RichMarkdown>
          ) : (
            <pre>{JSON.stringify(output, null, 2).slice(0, 500)}</pre>
          )
        ) : (
          <div className="card-placeholder">
            {isCurrentStep ? 'Running...' :
             isComplete ? 'Complete (no content captured)' :
             'Pending...'}
          </div>
        )}
      </div>

      {isCurrentStep && (
        <div className="shimmer-overlay" />
      )}
    </div>
  );
}

export default CellExplosionView;
