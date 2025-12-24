import React from 'react';
import PlaceholderView from '../_PlaceholderView';

/**
 * InterruptsView - Manage blocked sessions and checkpoints
 *
 * TODO: Implement interrupts dashboard with:
 * - List of blocked/waiting sessions
 * - HITL checkpoints needing responses
 * - Signal management
 * - Quick actions to unblock or cancel
 */
const InterruptsView = ({ navigate }) => {
  return (
    <PlaceholderView
      icon="mdi:hand-back-right"
      title="Interrupts"
      description="Manage blocked sessions, respond to human-in-the-loop checkpoints, and handle signals. Resume or cancel waiting cascades."
    />
  );
};

export default InterruptsView;
