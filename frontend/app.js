// Base API URL configuration
// Note: In production, this will point to your ALB
const API_BASE_URL = window.location.origin.includes('localhost')
    ? 'http://localhost:8000'
    : 'async-job-processing-alb-1919681779.eu-central-1.elb.amazonaws.com';

// DOM Element Selectors
const uploadForm = document.getElementById('upload-form');
const csvFileInput = document.getElementById('csv-file');
const uploadBtn = document.getElementById('upload-btn');

const statusCard = document.getElementById('status-card');
const jobIdDisplay = document.getElementById('job-id-display');
const jobStatusBadge = document.getElementById('job-status');
const jobMessage = document.getElementById('job-message');
const loadingSpinner = document.getElementById('loading-spinner');

const resultSection = document.getElementById('result-section');
const countValid = document.getElementById('count-valid');
const countUnderage = document.getElementById('count-underage');
const countInvalid = document.getElementById('count-invalid');

const downloadBox = document.getElementById('download-box');
const downloadLink = document.getElementById('download-link');

// Polling configuration
let pollingInterval = null;
const POLLING_INTERVAL_MS = 3000; // Poll every 3 seconds

// Event Listener for File Upload Form Submit
uploadForm.addEventListener('submit', async (event) => {
    event.preventDefault();

    const file = csvFileInput.files[0];
    if (!file) {
        alert('Please select a CSV file first.');
        return;
    }

    // Prepare Multipart Form Data
    const formData = new FormData();
    formData.append('file', file);

    try {
        // UI State: Uploading
        uploadBtn.disabled = true;
        uploadBtn.textContent = 'Uploading...';

        // HTTP POST Request to FastAPI /upload endpoint
        const response = await fetch(`${API_BASE_URL}/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to upload CSV file.');
        }

        const data = await response.json();
        
        // Reset Upload Button and Start Polling
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload & Submit Job';
        
        startJobTracking(data.job_id);

    } catch (error) {
        alert(`Upload Error: ${error.message}`);
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload & Submit Job';
    }
});

// Function to initialize Job Status Tracking
function startJobTracking(jobId) {
    // Reveal Status Section
    statusCard.style.display = 'block';
    resultSection.style.display = 'none';
    downloadBox.style.display = 'none';
    loadingSpinner.style.display = 'block';

    jobIdDisplay.textContent = jobId;
    updateStatusBadge('PENDING');
    jobMessage.textContent = 'Job received. Waiting for worker processing...';

    // Clear any active polling interval before starting a new one
    if (pollingInterval) clearInterval(pollingInterval);

    // Initial check
    checkJobStatus(jobId);

    // Start Polling (Periodic execution)
    pollingInterval = setInterval(() => {
        checkJobStatus(jobId);
    }, POLLING_INTERVAL_MS);
}

// Function to Query Job Status (GET /jobs/{job_id})
async function checkJobStatus(jobId) {
    try {
        const response = await fetch(`${API_BASE_URL}/jobs/${jobId}`);

        if (!response.ok) {
            throw new Error('Failed to fetch job status from server.');
        }

        const jobData = await response.json();
        updateStatusBadge(jobData.status);

        if (jobData.message) {
            jobMessage.textContent = jobData.message;
        }

        // Handle Terminal Job States
        if (jobData.status === 'COMPLETED') {
            stopPolling();
            renderResults(jobData);
        } else if (jobData.status === 'FAILED') {
            stopPolling();
            loadingSpinner.style.display = 'none';
            jobMessage.textContent = jobData.message || 'Job execution failed on worker.';
        }

    } catch (error) {
        console.error('Polling Error:', error);
    }
}

// Helper: Stop Polling
function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

// Helper: Dynamic Badge Styling
function updateStatusBadge(status) {
    jobStatusBadge.textContent = status;
    jobStatusBadge.className = 'badge ' + status.toLowerCase();
}

// Helper: Render Final Results and Download Link
function renderResults(jobData) {
    loadingSpinner.style.display = 'none';
    resultSection.style.display = 'block';

    if (jobData.result_summary) {
        countValid.textContent = jobData.result_summary.valid || 0;
        countUnderage.textContent = jobData.result_summary.underage || 0;
        countInvalid.textContent = jobData.result_summary.invalid_value || 0;
    }

    // If main.py generated a Presigned URL for invalid rows
    if (jobData.presigned_url) {
        downloadBox.style.display = 'block';
        downloadLink.href = jobData.presigned_url;
    }
}