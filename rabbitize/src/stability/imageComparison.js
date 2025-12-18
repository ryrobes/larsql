const sharp = require('sharp');
const chalk = require('chalk');

/**
 * Process a screenshot for comparison
 * @param {Buffer} screenshot - Raw screenshot buffer
 * @param {number} width - Target width for downscaling
 * @returns {Promise<Buffer>} Processed image buffer
 */
async function processScreenshot(screenshot, width) {
  //console.log(chalk.magenta('🐴 Stability:  Processing screenshot:', JSON.stringify({ targetWidth: width })));
  try {
    // Get original dimensions
    const metadata = await sharp(screenshot).metadata();

    // Process to raw RGB format and resize
    const processed = await sharp(screenshot)
      .resize(width, null, { fit: 'contain' })
      .removeAlpha()
      .toColorspace('srgb')
      .raw()
      .toBuffer({ resolveWithObject: true });

    // Calculate new height maintaining aspect ratio
    const height = Math.round((metadata.height * width) / metadata.width);

    // Verify we got RGB data
    const expectedSize = width * height * 3;
    if (processed.data.length !== expectedSize) {
      throw new Error(`Raw buffer size ${processed.data.length} does not match expected RGB size ${expectedSize}`);
    }

    // console.log(chalk.magenta('🐴 Stability:  Screenshot processed:', JSON.stringify({
    //   originalSize: screenshot.length,
    //   originalDimensions: { width: metadata.width, height: metadata.height },
    //   processedSize: processed.data.length,
    //   processedDimensions: { width, height },
    //   expectedSize,
    //   channels: 3
    // })));

    return {
      data: Buffer.from(processed.data),
      width,
      height
    };
  } catch (error) {
    console.error(chalk.magenta('🐴 Stability:  Failed to process screenshot:', JSON.stringify({
      error: error.message,
      stack: error.stack
    })));
    throw error;
  }
}

/**
 * Compare two processed screenshots using raw pixel comparison
 * @param {Buffer} img1 - First processed image buffer
 * @param {Buffer} img2 - Second processed image buffer
 * @param {number} width - Image width
 * @param {number} height - Image height
 * @param {number} threshold - Difference threshold (0-1)
 * @returns {Promise<boolean>} True if images are different
 */
async function compareScreenshots(img1, img2, width, height, threshold) {
  // Verify dimensions match
  if (img1.width !== width || img1.height !== height ||
      img2.width !== width || img2.height !== height) {
    throw new Error(`Image dimensions don't match: expected ${width}x${height}, got ${img1.width}x${img1.height} and ${img2.width}x${img2.height}`);
  }

  const totalPixels = width * height;
  // Convert the user's 0-1 threshold to a much smaller actual threshold
  // If user passes 0.1 (10%), we'll use 0.0001 (0.01%) instead
  const actualThreshold = threshold * 0.001; // Make 1000x more sensitive
  const maxDiffPixels = Math.floor(totalPixels * actualThreshold);
  let diffPixels = 0;

  // Compare raw RGB values
  const data1 = img1.data;
  const data2 = img2.data;

  // console.log(chalk.magenta('🐴 Stability:  Starting comparison:', JSON.stringify({
  //   dimensions: { width, height },
  //   userThreshold: threshold,
  //   actualThreshold,
  //   maxDiffPixels,
  //   percentOfTotal: (maxDiffPixels / totalPixels * 100).toFixed(4) + '%',
  //   bufferSizes: {
  //     img1: data1.length,
  //     img2: data2.length,
  //     expected: width * height * 3
  //   }
  // })));

  try {
    // Compare RGB values with minimal tolerance to catch subtle changes
    const tolerance = 1; // Minimal tolerance for direct RGB differences
    const colorVarianceTolerance = 2; // How much RGB values can vary before considering it "colored"

    for (let i = 0; i < data1.length; i += 3) {
      const r1 = data1[i];
      const g1 = data1[i + 1];
      const b1 = data1[i + 2];
      const r2 = data2[i];
      const g2 = data2[i + 1];
      const b2 = data2[i + 2];

      // Check for direct RGB differences
      if (Math.abs(r1 - r2) > tolerance ||
          Math.abs(g1 - g2) > tolerance ||
          Math.abs(b1 - b2) > tolerance) {
        diffPixels++;
      } else {
        // Even if direct RGB differences are small, check if one pixel is grayscale
        // while the other has color variation
        const isGray1 = Math.abs(r1 - g1) <= colorVarianceTolerance &&
                       Math.abs(g1 - b1) <= colorVarianceTolerance &&
                       Math.abs(r1 - b1) <= colorVarianceTolerance;
        const isGray2 = Math.abs(r2 - g2) <= colorVarianceTolerance &&
                       Math.abs(g2 - b2) <= colorVarianceTolerance &&
                       Math.abs(r2 - b2) <= colorVarianceTolerance;

        if (isGray1 !== isGray2) {
          diffPixels++;
        }
      }

      // Early exit if we've exceeded the threshold
      if (diffPixels > maxDiffPixels) {
        // console.log(chalk.magenta('🐴 Stability:  Comparison result:', JSON.stringify({
        //   diffPixels,
        //   maxDiffPixels,
        //   percentDifferent: (diffPixels / totalPixels * 100).toFixed(4) + '%',
        //   isDifferent: true,
        //   earlyExit: true
        // })));
        return true;
      }
    }

    const isDifferent = diffPixels > maxDiffPixels;
    // console.log(chalk.magenta('🐴 Stability:  Comparison result:', JSON.stringify({
    //   diffPixels,
    //   maxDiffPixels,
    //   percentDifferent: (diffPixels / totalPixels * 100).toFixed(4) + '%',
    //   isDifferent
    // })));

    return isDifferent;
  } catch (error) {
    console.error(chalk.magenta('🐴 Stability:  Comparison error:', JSON.stringify({
      error: error.message,
      stack: error.stack
    })));
    throw error;
  }
}

/**
 * Get dimensions of a processed image buffer
 * @param {Buffer} imageBuffer - Raw image buffer
 * @returns {Promise<{width: number, height: number}>}
 */
async function getImageDimensions(imageBuffer) {
  console.log(chalk.magenta('🐴 Stability:  Getting image dimensions'));
  try {
    const metadata = await sharp(imageBuffer).metadata();
    console.log(chalk.magenta('🐴 Stability:  Image dimensions:', JSON.stringify({
      width: metadata.width,
      height: metadata.height,
      channels: metadata.channels,
      format: metadata.format
    })));
    return {
      width: metadata.width,
      height: metadata.height
    };
  } catch (error) {
    console.error(chalk.magenta('🐴 Stability:  Failed to get image dimensions:', JSON.stringify({
      error: error.message,
      stack: error.stack
    })));
    throw error;
  }
}

module.exports = {
  processScreenshot,
  compareScreenshots,
  getImageDimensions
};