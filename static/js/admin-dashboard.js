/* =============================================
   CampusLink Admin Dashboard - JavaScript
   ============================================= */

// =============================================
// INITIALIZATION
// =============================================
document.addEventListener('DOMContentLoaded', () => {
  initProfileDropdown();
  initSidebarNavigation();
  loadDashboardData();
  var settingsForm = document.getElementById('adminSettingsForm');
  if (settingsForm) settingsForm.addEventListener('submit', saveSettings);
  var announcementForm = document.getElementById('announcementForm');
  if (announcementForm) {
    announcementForm.addEventListener('submit', function(e) {
      e.preventDefault();
      var id = document.getElementById('announcementId').value;
      var aud = [];
      if (document.getElementById('audStudent') && document.getElementById('audStudent').checked) aud.push('student');
      if (document.getElementById('audFaculty') && document.getElementById('audFaculty').checked) aud.push('faculty');
      if (document.getElementById('audAlumni') && document.getElementById('audAlumni').checked) aud.push('alumni');
      if (!aud.length) {
        showToast('Select at least one audience (Student, Faculty, or Alumni).', 'error');
        return;
      }
      var desc = (document.getElementById('announcementDescription').value || '').trim();
      if (!desc) {
        showToast('Description is required.', 'error');
        return;
      }
      var payload = {
        title: document.getElementById('announcementTitle').value,
        description: desc,
        date: document.getElementById('announcementDate').value || new Date().toISOString().slice(0, 10),
        audience: aud,
        visibility: 'all',
      };
      var url = '/api/admin/announcements';
      var method = 'POST';
      if (id) {
        url = '/api/admin/announcements/' + id;
        method = 'PUT';
      }
      fetch(url, { method: method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), credentials: 'same-origin' })
        .then(function(res) { return res.ok ? res.json() : Promise.reject(new Error('Failed to save')); })
        .then(function() {
          showToast('Announcement saved', 'success');
          document.getElementById('announcementFormSection').style.display = 'none';
          document.getElementById('announcementId').value = '';
          announcementForm.reset();
          loadAnnouncements();
        })
        .catch(function(err) { showToast(err.message || 'Failed to save', 'error'); });
    });
  }
  var btnCreate = document.getElementById('btnCreateAnnouncement');
  if (btnCreate) btnCreate.addEventListener('click', function() {
    document.getElementById('announcementId').value = '';
    document.getElementById('announcementFormTitle').textContent = 'Create Announcement';
    document.getElementById('announcementForm').reset();
    document.getElementById('announcementFormSection').style.display = 'block';
  });
  var btnCancel = document.getElementById('btnCancelAnnouncement');
  if (btnCancel) btnCancel.addEventListener('click', function() {
    document.getElementById('announcementFormSection').style.display = 'none';
  });
});

// =============================================
// PROFILE DROPDOWN
// =============================================
function initProfileDropdown() {
  const profileBtn = document.getElementById('adminProfileBtn');
  const dropdown = document.getElementById('profileDropdown');

  if (profileBtn && dropdown) {
    profileBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('show');
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', () => {
      dropdown.classList.remove('show');
    });
  }
}

// =============================================
// SIDEBAR NAVIGATION
// =============================================
function initSidebarNavigation() {
  const sidebarLinks = document.querySelectorAll('.sidebar-link[data-page]');
  
  sidebarLinks.forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const page = link.getAttribute('data-page');
      navigateToPage(page);
    });
  });
}

/**
 * Navigate to a specific page/view
 * @param {string} pageName - The page identifier
 */
function navigateToPage(pageName) {
  // Update active state in sidebar
  const sidebarLinks = document.querySelectorAll('.sidebar-link');
  sidebarLinks.forEach(link => {
    link.classList.remove('active');
    if (link.getAttribute('data-page') === pageName) {
      link.classList.add('active');
    }
  });

  // Hide all page views
  const pageViews = document.querySelectorAll('.page-view');
  pageViews.forEach(view => view.classList.remove('active'));

  // Show the selected page view
  const targetView = document.getElementById(`page-${pageName}`);
  if (targetView) {
    targetView.classList.add('active');
    
    // Load page-specific data
    loadPageData(pageName);
  }
}

/**
 * Load data for a specific page
 * @param {string} pageName - The page identifier
 */
function loadPageData(pageName) {
  switch (pageName) {
    case 'dashboard':
      loadDashboardData();
      break;
    case 'users':
      loadUserManagement();
      break;
    case 'students':
      loadStudentRecords();
      break;
    case 'faculty':
      loadFacultyList();
      break;
    case 'jobs':
      loadJobManagement();
      break;
    case 'announcements':
      loadAnnouncements();
      break;
    case 'reports':
      loadReports();
      break;
    case 'support':
      loadSupportTickets();
      break;
    case 'settings':
      loadSettings();
      break;
  }
}

// =============================================
// DASHBOARD OVERVIEW
// =============================================
async function loadDashboardData() {
  const token = localStorage.getItem('campuslink_token');
  
  try {
    // Fetch overview stats from API
    const res = await fetch('/api/admin/overview', {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });
    
    if (res.ok) {
      const data = await res.json();
      updateDashboardCards(data);
    }
  } catch (e) {
    console.error('Failed to load dashboard data', e);
  }
  
  // Load recent activities
  loadRecentActivities();
}

/**
 * Update dashboard summary cards and analytics with real data
 * @param {Object} data - The full overview API response (counts + analytics)
 */
function updateDashboardCards(data) {
  const counts = data.counts || data || {};
  const analytics = data.analytics || {};
  const el = (id) => document.getElementById(id);
  const set = (id, val) => { const e = el(id); if (e) e.textContent = val != null && val !== '' ? val : '—'; };
  set('totalStudents', counts.total_students);
  set('totalAlumni', counts.total_alumni);
  set('totalFaculty', counts.total_faculty);
  set('totalCoordinators', counts.total_coordinators);
  set('totalJobsPosted', counts.total_jobs_posted);
  set('totalApplications', counts.total_applications);
  set('placedStudents', counts.placed_students);
  set('eligibleStudents', counts.eligible_students);
  set('avgPlacementPrediction', counts.avg_placement_prediction != null ? counts.avg_placement_prediction + '%' : '—');
  set('activeJobsCount', counts.active_jobs);
  set('closedJobs', counts.closed_jobs);
  set('mostAppliedRole', counts.most_applied_job_role || '—');
  set('newRegistrationsMonth', counts.new_registrations_this_month);
  set('studentsCompleteProfiles', counts.students_complete_profiles);
  set('studentsIncompleteProfiles', counts.students_incomplete_profiles);
  if (analytics.job_postings_per_month && analytics.job_postings_per_month.length) {
    renderChart('chartJobPostings', analytics.job_postings_per_month, 'Job Postings', 'count');
  }
  if (analytics.student_registrations_per_month && analytics.student_registrations_per_month.length) {
    renderChart('chartStudentRegistrations', analytics.student_registrations_per_month, 'Registrations', 'count');
  }
  if (analytics.placement_prediction_distribution && analytics.placement_prediction_distribution.length) {
    renderDistributionChart('chartPlacementDistribution', analytics.placement_prediction_distribution);
  }
}

function renderChart(containerId, data, labelKey, valueKey) {
  const container = document.getElementById(containerId);
  if (!container || typeof Chart === 'undefined') return;
  const ctx = document.createElement('canvas');
  container.innerHTML = '';
  container.appendChild(ctx);
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.month),
      datasets: [{ label: labelKey, data: data.map(d => d[valueKey] || d.count), backgroundColor: 'rgba(59, 130, 246, 0.6)', borderColor: 'rgb(59, 130, 246)', borderWidth: 1 }]
    },
    options: { responsive: true, maintainAspectRatio: true, scales: { y: { beginAtZero: true } } }
  });
}

function renderDistributionChart(containerId, data) {
  const container = document.getElementById(containerId);
  if (!container || typeof Chart === 'undefined') return;
  const ctx = document.createElement('canvas');
  container.innerHTML = '';
  container.appendChild(ctx);
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.range),
      datasets: [{ label: 'Students', data: data.map(d => d.count), backgroundColor: 'rgba(16, 185, 129, 0.6)', borderColor: 'rgb(16, 185, 129)', borderWidth: 1 }]
    },
    options: { responsive: true, maintainAspectRatio: true, scales: { y: { beginAtZero: true } } }
  });
}

/**
 * Load recent activities for the dashboard
 */
async function loadRecentActivities() {
  const container = document.getElementById('recentActivities');
  if (!container) return;

  try {
    const token = localStorage.getItem('campuslink_token');
    const res = await fetch('/api/admin/activities', {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    });

    if (res.ok) {
      const data = await res.json();
      renderActivities(container, data.activities || []);
    } else {
      // Show placeholder if API not available
      renderActivities(container, []);
    }
  } catch (e) {
    console.error('Failed to load activities', e);
    renderActivities(container, []);
  }
}

/**
 * Render activity list
 * @param {HTMLElement} container - The container element
 * @param {Array} activities - Array of activity objects
 */
function renderActivities(container, activities) {
  if (!activities.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No recent activities</p>
      </div>
    `;
    return;
  }

  container.innerHTML = activities.map(activity => `
    <li class="activity-item">
      <div class="activity-icon">${getActivityIcon(activity.type)}</div>
      <div class="activity-content">
        <div class="activity-text">${escapeHtml(activity.message)}</div>
        <div class="activity-time">${formatTimeAgo(activity.created_at)}</div>
      </div>
    </li>
  `).join('');
}

// =============================================
// USER MANAGEMENT
// =============================================
let allUsers = [];

/**
 * Load all users for the User Management page
 */
async function loadUserManagement() {
  const tbody = document.getElementById('usersTableBody');
  const countEl = document.getElementById('userCount');
  
  if (!tbody) return;
  
  tbody.innerHTML = '<tr><td colspan="6" class="loading">Loading users...</td></tr>';
  
  try {
    const res = await fetch('/api/admin/users');
    
    if (!res.ok) {
      throw new Error('Failed to load users');
    }
    
    const data = await res.json();
    allUsers = data.users || [];
    
    if (countEl) {
      countEl.textContent = allUsers.length;
    }
    
    renderUsersTable(allUsers);
  } catch (e) {
    console.error('Failed to load users', e);
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Failed to load users</td></tr>';
  }
}

/**
 * Filter users based on selected filters
 */
function filterUsers() {
  const roleFilter = document.getElementById('userRoleFilter')?.value || '';
  const statusFilter = document.getElementById('userStatusFilter')?.value || '';
  const searchQuery = (document.getElementById('userSearchInput')?.value || '').toLowerCase();
  
  let filtered = allUsers;
  
  if (roleFilter) {
    filtered = filtered.filter(u => (u.role || '').toLowerCase() === roleFilter);
  }
  if (statusFilter) {
    filtered = filtered.filter(u => {
      if (statusFilter === 'blocked') return u.is_blocked;
      if (statusFilter === 'active') return !u.is_blocked;
      return true;
    });
  }
  if (searchQuery) {
    filtered = filtered.filter(u => {
      const name = (u.name || '').toLowerCase();
      const email = (u.email || '').toLowerCase();
      const dept = (u.department || u.branch || '').toLowerCase();
      const company = (u.current_company || '').toLowerCase();
      return name.includes(searchQuery) || email.includes(searchQuery) || dept.includes(searchQuery) || company.includes(searchQuery);
    });
  }
  
  const countEl = document.getElementById('userCount');
  if (countEl) countEl.textContent = filtered.length;
  renderUsersTable(filtered, roleFilter);
}

/**
 * Render users table (standard columns or alumni columns when roleFilter === 'alumni')
 * Faculty/Coordinator: no Verification column, no Verify/Reject actions
 * @param {Array} users - Array of user objects
 * @param {string} roleFilter - Current role filter (e.g. 'alumni')
 */
function renderUsersTable(users, roleFilter) {
  const tbody = document.getElementById('usersTableBody');
  const thead = document.getElementById('usersTableHead');
  if (!tbody) return;
  const isAlumniView = (roleFilter || '').toLowerCase() === 'alumni';

  if (isAlumniView && thead) {
    thead.innerHTML = '<th>Name</th><th>Email</th><th>Department</th><th>Graduation Year</th><th>Current Company</th><th>Job Role</th><th>Actions</th>';
  } else if (thead) {
    thead.innerHTML = '<th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Joined</th><th>Actions</th>';
  }

  if (!users.length) {
    tbody.innerHTML = '<tr><td colspan="' + (isAlumniView ? 7 : 6) + '" class="empty-state">No users found</td></tr>';
    return;
  }

  if (isAlumniView) {
    tbody.innerHTML = users.map(user => {
      const joinDate = user.created_at ? new Date(user.created_at).toLocaleDateString() : '—';
      return `
        <tr data-user-id="${user.id}">
          <td><strong>${escapeHtml(user.name || 'Unknown')}</strong></td>
          <td>${escapeHtml(user.email || '—')}</td>
          <td>${escapeHtml(user.department || user.branch || '—')}</td>
          <td>${escapeHtml(String(user.graduation_year || '—'))}</td>
          <td>${escapeHtml(user.current_company || '—')}</td>
          <td>${escapeHtml(user.job_role || '—')}</td>
          <td>
            <div class="action-btns">
              <button class="btn btn-sm btn-outline" onclick="viewUserDetails('${user.id}')">View</button>
              ${(user.role || '').toLowerCase() !== 'admin' ? `
                <button class="btn btn-sm ${user.is_blocked ? 'btn-success' : 'btn-warning'}" onclick="toggleUserBlock('${user.id}', ${!user.is_blocked})">${user.is_blocked ? 'Unblock' : 'Block'}</button>
              ` : ''}
            </div>
          </td>
        </tr>
      `;
    }).join('');
    return;
  }

  tbody.innerHTML = users.map(user => {
    const statusClass = user.is_blocked ? 'blocked' : 'active';
    const statusText = user.is_blocked ? 'Blocked' : 'Active';
    const roleClass = (user.role || 'student').toLowerCase();
    const joinDate = user.created_at ? new Date(user.created_at).toLocaleDateString() : '—';
    const blockBtn = (user.role || '').toLowerCase() !== 'admin'
      ? ` <button class="btn btn-sm ${user.is_blocked ? 'btn-success' : 'btn-warning'}" onclick="toggleUserBlock('${user.id}', ${!user.is_blocked})">${user.is_blocked ? 'Unblock' : 'Block'}</button> `
      : '';
    return `
      <tr data-user-id="${user.id}">
        <td><strong>${escapeHtml(user.name || 'Unknown')}</strong></td>
        <td>${escapeHtml(user.email || '—')}</td>
        <td><span class="role-badge ${roleClass}">${escapeHtml(user.role || 'student')}</span></td>
        <td><span class="status-badge ${statusClass}">${statusText}</span></td>
        <td>${joinDate}</td>
        <td><div class="action-btns"><button class="btn btn-sm btn-outline" onclick="viewUserDetails('${user.id}')">View</button>${blockBtn}</div></td>
      </tr>
    `;
  }).join('');
}

/**
 * View user details in a modal
 * @param {string} userId - User ID
 */
async function viewUserDetails(userId) {
  let user = allUsers.find(u => u.id === userId);
  if (!user) {
    try {
      const res = await fetch('/api/admin/users/' + userId, { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      user = data.user;
    } catch (e) {
      console.error(e);
      return;
    }
  }
  if (!user) return;
  
  const modalHtml = `
    <div class="modal-backdrop show" id="userDetailModal" onclick="closeUserModal(event)">
      <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-header">
          <h3 class="modal-title">User Details</h3>
          <button class="modal-close" onclick="closeUserModal()">&times;</button>
        </div>
        <div class="modal-body">
          <div class="user-detail-row">
            <div class="user-detail-label">Name</div>
            <div class="user-detail-value">${escapeHtml(user.name || 'Unknown')}</div>
          </div>
          <div class="user-detail-row">
            <div class="user-detail-label">Email</div>
            <div class="user-detail-value">${escapeHtml(user.email || '—')}</div>
          </div>
          <div class="user-detail-row">
            <div class="user-detail-label">Role</div>
            <div class="user-detail-value"><span class="role-badge ${user.role}">${escapeHtml(user.role || 'student')}</span></div>
          </div>
          <div class="user-detail-row">
            <div class="user-detail-label">Status</div>
            <div class="user-detail-value"><span class="status-badge ${user.is_blocked ? 'blocked' : 'active'}">${user.is_blocked ? 'Blocked' : 'Active'}</span></div>
          </div>
          <div class="user-detail-row">
            <div class="user-detail-label">Joined</div>
            <div class="user-detail-value">${user.created_at ? new Date(user.created_at).toLocaleString() : '—'}</div>
          </div>
          ${user.branch ? `
          <div class="user-detail-row">
            <div class="user-detail-label">Branch</div>
            <div class="user-detail-value">${escapeHtml(user.branch)}</div>
          </div>
          ` : ''}
          ${user.verification_status ? `
          <div class="user-detail-row">
            <div class="user-detail-label">Verification</div>
            <div class="user-detail-value">${escapeHtml(user.verification_status)}</div>
          </div>
          ` : ''}
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" onclick="closeUserModal()">Close</button>
          ${user.role !== 'admin' ? `
            <button class="btn ${user.is_blocked ? 'btn-success' : 'btn-danger'}" 
                    onclick="toggleUserBlock('${user.id}', ${!user.is_blocked}); closeUserModal();">
              ${user.is_blocked ? 'Unblock User' : 'Block User'}
            </button>
          ` : ''}
        </div>
      </div>
    </div>
  `;
  
  // Remove existing modal if any
  const existingModal = document.getElementById('userDetailModal');
  if (existingModal) existingModal.remove();
  
  // Add modal to page
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

/**
 * Close user detail modal
 * @param {Event} event - Click event (optional)
 */
function closeUserModal(event) {
  if (event && event.target !== event.currentTarget) return;
  const modal = document.getElementById('userDetailModal');
  if (modal) modal.remove();
}

/**
 * Toggle user block status
 * @param {string} userId - User ID
 * @param {boolean} block - Whether to block (true) or unblock (false)
 */
async function toggleUserBlock(userId, block) {
  const action = block ? 'block' : 'unblock';
  
  if (!confirm(`Are you sure you want to ${action} this user?`)) {
    return;
  }
  
  try {
    const res = await fetch(`/api/admin/users/${userId}/block`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ block })
    });
    
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `Failed to ${action} user`);
    }
    
    // Refresh the user list
    await loadUserManagement();
    showToast(`User ${action}ed successfully`, 'success');
  } catch (e) {
    console.error(`Failed to ${action} user`, e);
    showToast(e.message || `Failed to ${action} user`, 'error');
  }
}

// =============================================
// STUDENT RECORDS
// =============================================
let allStudents = [];
let studentBranches = new Set();

/**
 * Load all students for the Student Records page
 */
async function loadStudentRecords() {
  const tbody = document.getElementById('studentsTableBody');
  const countEl = document.getElementById('studentCount');
  
  if (!tbody) return;
  
  tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading students...</td></tr>';
  
  try {
    const res = await fetch('/api/admin/students');
    
    if (!res.ok) {
      throw new Error('Failed to load students');
    }
    
    const data = await res.json();
    allStudents = data.students || [];
    
    // Extract unique branches for filter
    studentBranches = new Set();
    allStudents.forEach(s => {
      if (s.branch) studentBranches.add(s.branch);
    });
    
    // Populate branch filter
    populateBranchFilter();
    
    if (countEl) {
      countEl.textContent = allStudents.length;
    }
    
    renderStudentsTable(allStudents);
  } catch (e) {
    console.error('Failed to load students', e);
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Failed to load students</td></tr>';
  }
}

/**
 * Populate branch filter dropdown
 */
function populateBranchFilter() {
  const select = document.getElementById('studentBranchFilter');
  if (!select) return;
  
  // Keep the "All Branches" option
  select.innerHTML = '<option value="">All Branches</option>';
  
  // Add branches
  Array.from(studentBranches).sort().forEach(branch => {
    const option = document.createElement('option');
    option.value = branch;
    option.textContent = branch;
    select.appendChild(option);
  });
}

/**
 * Filter students based on selected filters
 */
function filterStudents() {
  const branchFilter = document.getElementById('studentBranchFilter')?.value || '';
  const verificationFilter = document.getElementById('studentVerificationFilter')?.value || '';
  const profileFilter = document.getElementById('studentProfileFilter')?.value || '';
  const searchQuery = (document.getElementById('studentSearchInput')?.value || '').toLowerCase();
  
  let filtered = allStudents;
  
  // Filter by branch
  if (branchFilter) {
    filtered = filtered.filter(s => s.branch === branchFilter);
  }
  
  // Filter by verification status
  if (verificationFilter) {
    filtered = filtered.filter(s => {
      const status = (s.verification_status || 'pending').toLowerCase();
      return status === verificationFilter;
    });
  }
  
  // Filter by profile completion
  if (profileFilter) {
    filtered = filtered.filter(s => {
      const completion = s.profile_completion || 0;
      if (profileFilter === 'complete') return completion >= 80;
      if (profileFilter === 'partial') return completion >= 40 && completion < 80;
      if (profileFilter === 'incomplete') return completion < 40;
      return true;
    });
  }
  
  // Filter by search query
  if (searchQuery) {
    filtered = filtered.filter(s => {
      const name = (s.name || '').toLowerCase();
      const email = (s.email || '').toLowerCase();
      return name.includes(searchQuery) || email.includes(searchQuery);
    });
  }
  
  const countEl = document.getElementById('studentCount');
  if (countEl) {
    countEl.textContent = filtered.length;
  }
  
  renderStudentsTable(filtered);
}

/**
 * Render students table
 * @param {Array} students - Array of student objects
 */
function renderStudentsTable(students) {
  const tbody = document.getElementById('studentsTableBody');
  if (!tbody) return;
  
  if (!students.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No students found</td></tr>';
    return;
  }
  
  tbody.innerHTML = students.map(student => {
    const completion = student.profile_completion || 0;
    const progressClass = completion >= 80 ? 'high' : (completion >= 40 ? 'medium' : 'low');
    const verificationStatus = (student.verification_status || 'pending').toLowerCase();
    
    return `
      <tr>
        <td><strong>${escapeHtml(student.name || 'Unknown')}</strong></td>
        <td>${escapeHtml(student.email || '—')}</td>
        <td>${escapeHtml(student.branch || '—')}</td>
        <td>${student.cgpa ? student.cgpa.toFixed(2) : '—'}</td>
        <td>
          <div class="progress-bar">
            <div class="progress-track">
              <div class="progress-fill ${progressClass}" style="width: ${completion}%"></div>
            </div>
            <span class="progress-text">${completion}%</span>
          </div>
        </td>
        <td><span class="verification-badge ${verificationStatus}">${verificationStatus}</span></td>
        <td>
          <div class="action-btns">
            <button class="btn btn-sm btn-outline" onclick="viewStudentProfile('${student.id}')">View Profile</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

/**
 * View student profile (opens in new tab)
 * @param {string} studentId - Student ID
 */
function viewStudentProfile(studentId) {
  window.open(`/profile/${studentId}`, '_blank');
}

/**
 * Export students to CSV
 */
function exportStudents() {
  if (!allStudents.length) {
    showToast('No students to export', 'warning');
    return;
  }
  
  // Create CSV content
  const headers = ['Name', 'Email', 'Branch', 'CGPA', 'Profile Completion', 'Verification Status'];
  const rows = allStudents.map(s => [
    s.name || '',
    s.email || '',
    s.branch || '',
    s.cgpa || '',
    (s.profile_completion || 0) + '%',
    s.verification_status || 'pending'
  ]);
  
  const csvContent = [
    headers.join(','),
    ...rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
  ].join('\n');
  
  // Download file
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `students_${new Date().toISOString().split('T')[0]}.csv`;
  link.click();
  
  showToast('Students exported successfully', 'success');
}

async function loadFacultyList() {
  const facultyEl = document.getElementById('admin-faculty-list');
  const coordEl = document.getElementById('admin-coordinator-list');
  if (!facultyEl || !coordEl) return;
  facultyEl.textContent = 'Loading...';
  facultyEl.classList.remove('empty-state');
  coordEl.textContent = 'Loading...';
  coordEl.classList.remove('empty-state');
  try {
    const res = await fetch('/api/admin/faculty-and-coordinators', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to load');
    const data = await res.json();
    const faculty = data.faculty || [];
    const coordinators = data.coordinators || [];
    if (faculty.length === 0) {
      facultyEl.innerHTML = '<div class="empty-state"><p>No faculty found. They will appear here when they register.</p></div>';
      facultyEl.classList.add('empty-state');
    } else {
      facultyEl.innerHTML = '<table class="data-table"><thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Role</th><th>Actions</th></tr></thead><tbody>' +
        faculty.map(f => '<tr><td>' + escapeHtml(f.name) + '</td><td>' + escapeHtml(f.email) + '</td><td>' + escapeHtml(f.department || f.branch || '—') + '</td><td><span class="role-badge faculty">Faculty</span></td><td><div class="action-btns"><button class="btn btn-sm btn-outline" onclick="viewUserDetails(\'' + f.id + '\')">View</button> <button class="btn btn-sm btn-danger" onclick="removeFacultyOrCoordinator(\'' + f.id + '\', \'faculty\')">Remove</button></div></td></tr>').join('') +
        '</tbody></table>';
    }
    if (coordinators.length === 0) {
      coordEl.innerHTML = '<div class="empty-state"><p>No coordinators yet. They will appear here when they register.</p></div>';
      coordEl.classList.add('empty-state');
    } else {
      coordEl.innerHTML = '<table class="data-table"><thead><tr><th>Name</th><th>Email</th><th>Department</th><th>Role</th><th>Actions</th></tr></thead><tbody>' +
        coordinators.map(c => '<tr><td>' + escapeHtml(c.name) + '</td><td>' + escapeHtml(c.email) + '</td><td>' + escapeHtml(c.department || c.branch || '—') + '</td><td><span class="role-badge coordinator">Coordinator</span></td><td><div class="action-btns"><button class="btn btn-sm btn-outline" onclick="viewUserDetails(\'' + c.id + '\')">View</button> <button class="btn btn-sm btn-danger" onclick="removeFacultyOrCoordinator(\'' + c.id + '\', \'coordinator\')">Remove</button></div></td></tr>').join('') +
        '</tbody></table>';
    }
  } catch (e) {
    facultyEl.textContent = (e && e.message) || 'Failed to load faculty.';
    facultyEl.classList.add('error-state');
    coordEl.textContent = (e && e.message) || 'Failed to load coordinators.';
    coordEl.classList.add('error-state');
  }
}

async function removeFacultyOrCoordinator(userId, roleLabel) {
  if (!confirm('Remove this ' + roleLabel + '? This action cannot be undone.')) return;
  try {
    const res = await fetch('/api/admin/users/' + userId, { method: 'DELETE', credentials: 'same-origin' });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.error || 'Failed to remove');
    }
    showToast(roleLabel + ' removed successfully', 'success');
    loadFacultyList();
  } catch (e) {
    showToast(e.message || 'Failed to remove', 'error');
  }
}

async function loadJobManagement() {
  const el = document.getElementById('admin-jobs-list');
  if (!el) return;
  el.textContent = 'Loading...';
  el.classList.remove('empty-state');
  try {
    const res = await fetch('/api/admin/jobs', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to load');
    const data = await res.json();
    const jobs = data.jobs || [];
    if (jobs.length === 0) {
      el.innerHTML = '<div class="empty-state"><p>No jobs posted yet.</p></div>';
      el.classList.add('empty-state');
    } else {
      el.innerHTML = '<table class="data-table"><thead><tr><th>Source</th><th>Company</th><th>Role</th><th>Type</th><th>Location</th><th>Posted</th></tr></thead><tbody>' +
        jobs.map(j => '<tr><td><span class="role-badge ' + (j.source === 'alumni' ? 'alumni' : 'coordinator') + '">' + escapeHtml(j.source) + '</span></td><td>' + escapeHtml(j.company || '—') + '</td><td>' + escapeHtml(j.role || '—') + '</td><td>' + escapeHtml(j.job_type || '—') + '</td><td>' + escapeHtml(j.location || '—') + '</td><td>' + (j.created_at ? new Date(j.created_at).toLocaleDateString() : '—') + '</td></tr>').join('') +
        '</tbody></table>';
    }
  } catch (e) {
    el.textContent = (e && e.message) || 'Failed to load jobs.';
    el.classList.add('error-state');
  }
}

function loadAnnouncements() {
  const listEl = document.getElementById('announcementsList');
  if (!listEl) return;
  listEl.innerHTML = '<div class="loading">Loading announcements...</div>';
  fetch('/api/admin/announcements', { credentials: 'same-origin' })
    .then(res => res.ok ? res.json() : Promise.reject(new Error('Failed to load')))
    .then(data => {
      const announcements = data.announcements || [];
      if (!announcements.length) {
        listEl.innerHTML = '<div class="empty-state"><p>No announcements yet. Create one to get started.</p></div>';
        return;
      }
      listEl.innerHTML = '<table class="data-table"><thead><tr><th>Title</th><th>Date</th><th>Audience</th><th>Actions</th></tr></thead><tbody>' +
        announcements.map(a => '<tr><td><strong>' + escapeHtml(a.title) + '</strong></td><td>' + (a.date ? new Date(a.date).toLocaleDateString() : '—') + '</td><td><span class="role-badge all">' + escapeHtml((a.audience && a.audience.length) ? a.audience.join(', ') : (a.visibility || 'all')) + '</span></td><td><div class="action-btns"><button class="btn btn-sm btn-outline" onclick="editAnnouncement(\'' + a.id + '\')">Edit</button> <button class="btn btn-sm btn-danger" onclick="deleteAnnouncement(\'' + a.id + '\')">Delete</button></div></td></tr>').join('') +
        '</tbody></table>';
    })
    .catch(() => { listEl.innerHTML = '<div class="empty-state"><p>Failed to load announcements.</p></div>'; });
}

function editAnnouncement(id) {
  fetch('/api/admin/announcements', { credentials: 'same-origin' })
    .then(res => res.json())
    .then(data => {
      const a = (data.announcements || []).find(x => x.id === id);
      if (!a) return;
      document.getElementById('announcementId').value = a.id;
      document.getElementById('announcementTitle').value = a.title || '';
      document.getElementById('announcementDescription').value = a.description || '';
      document.getElementById('announcementDate').value = a.date ? a.date.slice(0, 10) : '';
      var aud = a.audience || [];
      if (document.getElementById('audStudent')) document.getElementById('audStudent').checked = aud.indexOf('student') !== -1;
      if (document.getElementById('audFaculty')) document.getElementById('audFaculty').checked = aud.indexOf('faculty') !== -1;
      if (document.getElementById('audAlumni')) document.getElementById('audAlumni').checked = aud.indexOf('alumni') !== -1;
      if (!aud.length && a.visibility === 'students') {
        if (document.getElementById('audStudent')) document.getElementById('audStudent').checked = true;
        if (document.getElementById('audFaculty')) document.getElementById('audFaculty').checked = false;
        if (document.getElementById('audAlumni')) document.getElementById('audAlumni').checked = false;
      } else if (!aud.length && a.visibility === 'alumni') {
        if (document.getElementById('audStudent')) document.getElementById('audStudent').checked = false;
        if (document.getElementById('audFaculty')) document.getElementById('audFaculty').checked = false;
        if (document.getElementById('audAlumni')) document.getElementById('audAlumni').checked = true;
      } else if (!aud.length) {
        if (document.getElementById('audStudent')) document.getElementById('audStudent').checked = true;
        if (document.getElementById('audFaculty')) document.getElementById('audFaculty').checked = true;
        if (document.getElementById('audAlumni')) document.getElementById('audAlumni').checked = true;
      }
      document.getElementById('announcementFormTitle').textContent = 'Edit Announcement';
      document.getElementById('announcementFormSection').style.display = 'block';
    });
}

async function deleteAnnouncement(id) {
  if (!confirm('Delete this announcement?')) return;
  try {
    const res = await fetch('/api/admin/announcements/' + id, { method: 'DELETE', credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to delete');
    showToast('Announcement deleted', 'success');
    loadAnnouncements();
  } catch (e) {
    showToast(e.message || 'Failed to delete', 'error');
  }
}

function loadReports() {
  // Reports: redirect to dashboard analytics
}

function loadSettings() {
  const form = document.getElementById('adminSettingsForm');
  if (!form) return;
  fetch('/api/admin/settings', { credentials: 'same-origin' })
    .then(res => res.ok ? res.json() : Promise.reject())
    .then(data => {
      const s = data.settings || {};
      const setCheck = (id, val) => { const e = document.getElementById(id); if (e) e.checked = !!val; };
      const setVal = (id, val) => { const e = document.getElementById(id); if (e) e.value = val != null ? val : ''; };
      const p = s.platform || {};
      setCheck('setting_student_registration', p.enable_student_registration);
      setCheck('setting_alumni_registration', p.enable_alumni_registration);
      setCheck('setting_job_posting', p.enable_job_posting);
      setVal('setting_max_resume_size', p.max_resume_size_mb);
      setCheck('setting_placement_visible', p.placement_predictor_visible);
      const v = s.verification || {};
      setCheck('setting_student_verification', v.enable_student_verification);
      setCheck('setting_faculty_approval', v.enable_faculty_approval_requirement);
      setCheck('setting_auto_approve_alumni', v.auto_approve_alumni);
      const r = s.resume || {};
      setVal('setting_resume_template', r.resume_template);
      setCheck('setting_auto_generate_resume', r.auto_generate_resume);
      setCheck('setting_allow_resume_download', r.allow_resume_download);
      const pp = s.placement_predictor || {};
      setCheck('setting_placement_enabled', pp.enabled);
      setVal('setting_min_profile_completion', pp.min_profile_completion);
      setVal('setting_min_cgpa', pp.min_cgpa_required);
      const n = s.notifications || {};
      setCheck('setting_email_notifications', n.email_notifications);
      setCheck('setting_job_alerts', n.job_alert_notifications);
      setCheck('setting_placement_alerts', n.placement_update_alerts);
    })
    .catch(() => {});
}

function saveSettings(e) {
  if (e) e.preventDefault();
  const getCheck = (id) => !!document.getElementById(id)?.checked;
  const getVal = (id) => document.getElementById(id)?.value;
  const settings = {
    platform: {
      enable_student_registration: getCheck('setting_student_registration'),
      enable_alumni_registration: getCheck('setting_alumni_registration'),
      enable_job_posting: getCheck('setting_job_posting'),
      max_resume_size_mb: parseInt(getVal('setting_max_resume_size'), 10) || 5,
      placement_predictor_visible: getCheck('setting_placement_visible'),
    },
    verification: {
      enable_student_verification: getCheck('setting_student_verification'),
      enable_faculty_approval_requirement: getCheck('setting_faculty_approval'),
      auto_approve_alumni: getCheck('setting_auto_approve_alumni'),
    },
    resume: {
      resume_template: getVal('setting_resume_template') || 'default',
      auto_generate_resume: getCheck('setting_auto_generate_resume'),
      allow_resume_download: getCheck('setting_allow_resume_download'),
    },
    placement_predictor: {
      enabled: getCheck('setting_placement_enabled'),
      min_profile_completion: parseInt(getVal('setting_min_profile_completion'), 10) || 40,
      min_cgpa_required: parseFloat(getVal('setting_min_cgpa')) || 0,
    },
    notifications: {
      email_notifications: getCheck('setting_email_notifications'),
      job_alert_notifications: getCheck('setting_job_alerts'),
      placement_update_alerts: getCheck('setting_placement_alerts'),
    },
  };
  fetch('/api/admin/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
    credentials: 'same-origin',
  })
    .then(res => res.ok ? res.json() : Promise.reject())
    .then(() => showToast('Settings saved', 'success'))
    .catch(() => showToast('Failed to save settings', 'error'));
}

// =============================================
// UTILITY FUNCTIONS
// =============================================

/**
 * Get icon for activity type
 * @param {string} type - Activity type
 * @returns {string} Emoji icon
 */
function getActivityIcon(type) {
  const icons = {
    'student_registered': '👤',
    'faculty_added': '👨‍🏫',
    'job_posted': '💼',
    'job_approved': '✅',
    'user_blocked': '🚫',
    'default': '📋'
  };
  return icons[type] || icons.default;
}

/**
 * Format date to time ago string
 * @param {string} dateStr - ISO date string
 * @returns {string} Formatted time ago
 */
function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  
  let utcStr = dateStr;
  if (!dateStr.endsWith('Z') && !dateStr.includes('+')) {
    utcStr = dateStr + 'Z';
  }
  
  const date = new Date(utcStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

/**
 * Escape HTML to prevent XSS
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

/**
 * Show toast notification
 * @param {string} message - Message to display
 * @param {string} type - Type (success, error, warning)
 */
function showToast(message, type = 'success') {
  // Simple alert for now, can be enhanced
  alert(message);
}

// =============================================
// SOS / SUPPORT TICKETS
// =============================================
async function loadSupportTickets() {
  const body = document.getElementById('supportTicketsBody');
  if (!body) return;
  body.innerHTML = '<tr><td colspan="8" class="loading">Loading…</td></tr>';
  const st = (document.getElementById('supportFilterStatus') || {}).value || '';
  const pr = (document.getElementById('supportFilterPriority') || {}).value || '';
  const rl = (document.getElementById('supportFilterRole') || {}).value || '';
  const q = new URLSearchParams();
  if (st) q.set('status', st);
  if (pr) q.set('priority', pr);
  if (rl) q.set('role', rl);
  const token = localStorage.getItem('campuslink_token');
  try {
    const res = await fetch('/api/admin/support/tickets?' + q.toString(), {
      credentials: 'same-origin',
      headers: token ? { Authorization: 'Bearer ' + token } : {},
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      body.innerHTML = '<tr><td colspan="8" class="loading">' + escapeHtml(data.error || 'Failed to load') + '</td></tr>';
      return;
    }
    const items = data.tickets || [];
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="8" class="loading">No tickets match filters.</td></tr>';
      return;
    }
    body.innerHTML = items.map(function (t) {
      return '<tr data-support-id="' + escapeHtml(t.id) + '" style="cursor:pointer;">' +
        '<td><strong>' + escapeHtml(t.ticket_number) + '</strong></td>' +
        '<td>' + escapeHtml(t.user_name || '') + '<br/><small class="text-muted">' + escapeHtml(t.user_email || '') + '</small></td>' +
        '<td>' + escapeHtml(t.role || '') + '</td>' +
        '<td>' + escapeHtml(t.title || '') + '</td>' +
        '<td><span class="support-pri support-pri-' + escapeHtml((t.priority || '').toLowerCase()) + '">' + escapeHtml(t.priority || '') + '</span></td>' +
        '<td>' + escapeHtml((t.status || '').replace(/_/g, ' ')) + '</td>' +
        '<td>' + escapeHtml(t.updated_at || '') + '</td>' +
        '<td><button type="button" class="btn btn-secondary btn-sm" data-open-support="' + escapeHtml(t.id) + '">Open</button></td></tr>';
    }).join('');
    body.querySelectorAll('[data-open-support]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        openSupportTicketModal(btn.getAttribute('data-open-support'));
      });
    });
    body.querySelectorAll('tr[data-support-id]').forEach(function (row) {
      row.addEventListener('click', function () {
        openSupportTicketModal(row.getAttribute('data-support-id'));
      });
    });
  } catch (e) {
    body.innerHTML = '<tr><td colspan="8" class="loading">Network error</td></tr>';
  }
}

function closeSupportModal() {
  const m = document.getElementById('supportTicketModal');
  if (m) m.style.display = 'none';
}

async function openSupportTicketModal(ticketId) {
  const modal = document.getElementById('supportTicketModal');
  const titleEl = document.getElementById('supportModalTitle');
  const bodyEl = document.getElementById('supportModalBody');
  if (!modal || !bodyEl) return;
  modal.style.display = 'block';
  bodyEl.innerHTML = '<p class="text-muted">Loading…</p>';
  const token = localStorage.getItem('campuslink_token');
  try {
    const res = await fetch('/api/admin/support/tickets/' + encodeURIComponent(ticketId), {
      credentials: 'same-origin',
      headers: token ? { Authorization: 'Bearer ' + token } : {},
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      bodyEl.innerHTML = '<p class="text-muted">' + escapeHtml(data.error || 'Failed') + '</p>';
      return;
    }
    const t = data.ticket;
    if (titleEl) titleEl.textContent = t.ticket_number + ' — ' + (t.title || '');
    const msgs = (t.messages || []).map(function (m) {
      var side = m.is_staff ? 'support-msg-staff' : 'support-msg-user';
      return '<div class="support-msg ' + side + '"><div class="support-msg-who">' + escapeHtml(m.sender_name || '') + '</div>' +
        escapeHtml(m.message || '') + '<div class="support-msg-time">' + escapeHtml(m.created_at || '') + '</div></div>';
    }).join('');
    var shot = t.screenshot_url ? '<p><a href="' + escapeHtml(t.screenshot_url) + '" target="_blank" rel="noopener">Screenshot</a></p>' +
      '<img src="' + escapeHtml(t.screenshot_url) + '" alt="" class="support-shot" />' : '';
    bodyEl.innerHTML =
      '<p class="text-muted">' + escapeHtml(t.user_name || '') + ' · ' + escapeHtml(t.user_email || '') + ' · ' + escapeHtml(t.role || '') + '</p>' +
      '<div class="support-status-row"><label>Status</label> ' +
      '<select id="supportModalStatus">' +
      ['open', 'in_progress', 'resolved', 'closed'].map(function (s) {
        return '<option value="' + s + '"' + (t.status === s ? ' selected' : '') + '>' + s.replace(/_/g, ' ') + '</option>';
      }).join('') +
      '</select> <button type="button" class="btn btn-primary btn-sm" id="supportSaveStatus">Update status</button></div>' +
      '<h3 style="margin:16px 0 8px;font-size:14px;">Description</h3>' +
      '<p style="white-space:pre-wrap;font-size:14px;">' + escapeHtml(t.description || '') + '</p>' +
      shot +
      '<h3 style="margin:16px 0 8px;font-size:14px;">Thread</h3><div class="support-thread">' + msgs + '</div>' +
      '<div style="margin-top:16px;"><label>Reply as support</label>' +
      '<textarea id="supportAdminReply" rows="3" style="width:100%;margin-top:6px;padding:8px;border-radius:8px;border:1px solid var(--border);"></textarea>' +
      '<button type="button" class="btn btn-primary" style="margin-top:8px;" id="supportSendReply">Send reply</button></div>';

    document.getElementById('supportSaveStatus').addEventListener('click', async function () {
      var sel = document.getElementById('supportModalStatus');
      var st = sel ? sel.value : '';
      const r = await fetch('/api/admin/support/tickets/' + encodeURIComponent(ticketId), {
        method: 'PATCH',
        credentials: 'same-origin',
        headers: Object.assign(
          { 'Content-Type': 'application/json' },
          token ? { Authorization: 'Bearer ' + token } : {}
        ),
        body: JSON.stringify({ status: st }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        showToast('Status updated', 'success');
        loadSupportTickets();
      } else {
        showToast(j.error || 'Failed', 'error');
      }
    });

    document.getElementById('supportSendReply').addEventListener('click', async function () {
      var ta = document.getElementById('supportAdminReply');
      var txt = (ta && ta.value) || '';
      if (!txt.trim()) return;
      const r = await fetch('/api/admin/support/tickets/' + encodeURIComponent(ticketId) + '/messages', {
        method: 'POST',
        credentials: 'same-origin',
        headers: Object.assign(
          { 'Content-Type': 'application/json' },
          token ? { Authorization: 'Bearer ' + token } : {}
        ),
        body: JSON.stringify({ message: txt }),
      });
      const j = await r.json().catch(() => ({}));
      if (r.ok) {
        ta.value = '';
        showToast('Reply sent', 'success');
        openSupportTicketModal(ticketId);
        loadSupportTickets();
      } else {
        showToast(j.error || 'Failed', 'error');
      }
    });
  } catch (e) {
    bodyEl.innerHTML = '<p class="text-muted">Network error</p>';
  }
}

window.closeSupportModal = closeSupportModal;

// =============================================
// LOGOUT
// =============================================
function logout() {
  if (window.CampusLinkAuthSync && window.CampusLinkAuthSync.logoutEverywhere) {
    window.CampusLinkAuthSync.logoutEverywhere();
    return;
  }
  window.location.href = '/logout';
}
