#!/usr/bin/env node
import 'dotenv/config';

// Parse command line arguments first
const args = process.argv.slice(2);
const scriptName = args[0] || 'stdio';

async function run() {
  try {
    // Dynamically import only the requested module to prevent all modules from initializing
    switch (scriptName) {
      case 'stdio':
        // Import and run the stdio server
        await import('./stdio.js');
        break;
      case 'http':
        // Import and run the HTTP server
        await import('./httpServer.js');
        break;
      default:
        console.error(`Unknown script: ${scriptName}`);
        console.log('Available scripts:');
        console.log('- stdio');
        console.log('- http');
        process.exit(1);
    }
  } catch (error) {
    console.error('Error running script:', error);
    process.exit(1);
  }
}

run();
