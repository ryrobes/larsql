async function quickEnd() {
  try {
    // Essential cleanup only
    if (this.page) {
      await this.page.close().catch(() => {});
    }
    if (this.context) {
      await this.context.close().catch(() => {});
    }
    if (this.browser) {
      await this.browser.close().catch(() => {});
    }

    // Clear metrics interval
    if (this.metricsInterval) {
      clearInterval(this.metricsInterval);
      this.metricsInterval = null;
    }

    // Log state update
    if (this.firebase) {
      await this.firebase.setRunningState(false);
      await this.firebase.setPhase('complete');
    }

    return { success: true };
  } catch (error) {
    if (this.firebase) {
      this.firebase.error('Quick end process failed:', error);
    } else {
      console.error('Quick end process failed:', error);
    }
    return { success: false, error: error.message };
  }
}

module.exports = {
  quickEnd
};