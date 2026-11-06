var langNames = {tr:'Turkish', ru:'Russian', de:'German', en:'English'};
var currentSetId = null;
var currentSetData = null;
var activeTab = 'my-sets';
var addWordsState = { available: [], alreadyIds: new Set(), selected: new Set(), filter: '' };

// Tabs
function showTab(tab) {
    activeTab = tab;
    document.querySelectorAll('.tab').forEach(function(t) {
        var on = t.getAttribute('data-tab') === tab;
        t.classList.toggle('active', on);
        if (on) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
    });
    if (window.location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
    document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); s.style.display = 'none'; });
    var sec = document.getElementById('sec-' + tab);
    if (sec) { sec.classList.add('active'); sec.style.display = 'block'; }

    if (tab === 'my-sets') loadMySets();
    if (tab === 'browse') loadBrowse();
    if (tab === 'friends') loadFriends();
}

// Load my sets
async function loadMySets() {
    try {
        var r = await fetch('/api/sets/list');
        var d = await r.json();
        if (d.error) { document.getElementById('mySetsGrid').innerHTML = '<div class="empty-state"><h3>Log in required</h3><p>Create an account to manage flashcard sets</p></div>'; return; }
        if (d.sets.length === 0) { document.getElementById('mySetsGrid').innerHTML = '<div class="empty-state"><h3>No sets yet</h3><p>Create a set to organize your saved vocabulary</p></div>'; return; }
        document.getElementById('mySetsGrid').innerHTML = d.sets.map(function(s) {
            var badges = '<span class="set-badge badge-count">' + wordCount(s.word_count) + '</span>';
            if (s.is_public) badges += '<span class="set-badge badge-public">public</span>';
            else badges += '<span class="set-badge badge-private">private</span>';
            if (s.target_lang) badges += '<span class="set-badge badge-lang">' + (langNames[s.target_lang] || s.target_lang) + '</span>';
            return '<div class="set-card" role="button" tabindex="0" onclick="openSet(' + s.id + ')" onkeydown="onCardKey(event, ' + s.id + ')"><div class="set-name">' + escapeHtml(s.name) + '</div>' +
                (s.description ? '<div class="set-desc">' + escapeHtml(s.description) + '</div>' : '') +
                '<div class="set-meta">' + badges + '</div></div>';
        }).join('');
    } catch(e) { console.error(e); }
}

// Load public sets
async function loadBrowse() {
    try {
        var r = await fetch('/api/sets/browse');
        var d = await r.json();
        if (d.sets.length === 0) { document.getElementById('browseGrid').innerHTML = '<div class="empty-state"><h3>No public sets yet</h3><p>Public sets from other users will appear here</p></div>'; return; }
        var meId = null;
        try {
            var me = await fetch('/api/auth/me');
            var meData = await me.json();
            if (meData.user) meId = meData.user.id;
        } catch(e) {}
        document.getElementById('browseGrid').innerHTML = d.sets.map(function(s) {
            var badges = '<span class="set-badge badge-count">' + wordCount(s.word_count) + '</span>';
            if (s.target_lang) badges += '<span class="set-badge badge-lang">' + (langNames[s.target_lang] || s.target_lang) + '</span>';
            var canFork = meId && s.user_id !== meId && (s.word_count || 0) > 0;
            var forkBtn = canFork ? '<button class="btn btn-primary set-card-fork" onclick="event.stopPropagation();quickForkSet(' + s.id + ', this)">+ Save</button>' : '';
            return '<div class="set-card" role="button" tabindex="0" onclick="openSet(' + s.id + ')" onkeydown="onCardKey(event, ' + s.id + ')"><div class="set-name">' + escapeHtml(s.name) + '</div>' +
                (s.description ? '<div class="set-desc">' + escapeHtml(s.description) + '</div>' : '') +
                '<div class="set-meta">' + badges + '</div>' +
                '<div class="set-owner">by ' + escapeHtml(s.owner_name || 'Unknown') + forkBtn + '</div></div>';
        }).join('');
    } catch(e) { console.error(e); }
}

async function quickForkSet(setId, btn) {
    if (!btn || btn.disabled) return;
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
        var r = await fetch('/api/sets/' + setId + '/fork', { method: 'POST' });
        var d = await r.json();
        if (d.error) {
            btn.textContent = 'Error';
            setTimeout(function(){ btn.disabled = false; btn.textContent = originalText; }, 1500);
            return;
        }
        btn.textContent = 'Saved';
    } catch(e) {
        btn.textContent = 'Error';
        setTimeout(function(){ btn.disabled = false; btn.textContent = originalText; }, 1500);
    }
}

// Open set detail
async function openSet(setId) {
    try {
        var r = await fetch('/api/sets/' + setId);
        var d = await r.json();
        if (d.error) { showToast(d.error); return; }
        currentSetId = setId;
        currentSetData = d.set;

        document.getElementById('detailTitle').textContent = d.set.name;
        document.getElementById('detailDesc').textContent = d.set.description || '';

        var meta = '<span class="set-badge badge-count">' + wordCount(d.words.length) + '</span>';
        if (d.set.is_public) meta += '<span class="set-badge badge-public">public</span>';
        else meta += '<span class="set-badge badge-private">private</span>';
        if (d.set.target_lang) meta += '<span class="set-badge badge-lang">' + (langNames[d.set.target_lang] || d.set.target_lang) + '</span>';
        if (d.set.owner_name) meta += '<span style="font-size:12px;color:var(--text-3);margin-left:8px;">by ' + escapeHtml(d.set.owner_name) + '</span>';
        document.getElementById('detailMeta').innerHTML = meta;

        // Check if it's the user's own set
        var isOwner = true; // We'll assume owner if we can see delete button
        try {
            var me = await fetch('/api/auth/me');
            var meData = await me.json();
            isOwner = meData.user && meData.user.id === d.set.user_id;
        } catch(e) { isOwner = false; }

        document.getElementById('deleteSetBtn').style.display = isOwner ? 'inline-flex' : 'none';
        document.getElementById('togglePublicBtn').style.display = isOwner ? 'inline-flex' : 'none';
        document.getElementById('addWordsBtn').style.display = isOwner ? 'inline-flex' : 'none';
        document.getElementById('togglePublicBtn').textContent = d.set.is_public ? 'Make private' : 'Make public';
        document.getElementById('studyBtn').style.display = (isOwner && d.words.length > 0) ? 'inline-flex' : 'none';
        var canFork = (!isOwner) && d.set.is_public && d.words.length > 0;
        document.getElementById('saveToLibraryBtn').style.display = canFork ? 'inline-flex' : 'none';

        if (d.words.length === 0) {
            document.getElementById('detailWords').innerHTML = '<div class="empty-state"><p>' + (isOwner ? 'No words in this set yet. Click "Add words" above to pick from your saved vocabulary.' : 'No words in this public set yet.') + '</p></div>';
        } else {
            document.getElementById('detailWords').innerHTML = d.words.map(function(w) {
                var tags = '<span class="word-tag tag-pos">' + escapeHtml(w.pos) + '</span>';
                if (w.grammatical_case) tags += '<span class="word-tag tag-case">' + escapeHtml(w.grammatical_case) + '</span>';
                if (w.difficulty) tags += '<span class="word-tag tag-cefr cefr-' + escapeHtml(w.difficulty) + '">' + escapeHtml(w.difficulty) + '</span>';
                var removeBtn = isOwner ? '<button class="word-remove" type="button" aria-label="Remove from set" onclick="event.stopPropagation();removeFromSet(' + currentSetId + ',' + w.id + ')">&times;</button>' : '';
                return '<div class="word-row"><div class="word-main"><div class="word-text">' + escapeHtml(w.word) + '</div><div class="word-meaning">' + escapeHtml(w.meaning) + '</div><div class="word-tags">' + tags + '</div></div>' + removeBtn + '</div>';
            }).join('');
        }

        // Hide tabs, show detail
        document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); s.style.display = 'none'; });
        document.getElementById('sec-detail').style.display = 'block';
        document.querySelector('.tabs').style.display = 'none';
    } catch(e) { console.error(e); }
}

function closeDetail() {
    document.getElementById('sec-detail').style.display = 'none';
    document.querySelector('.tabs').style.display = 'flex';
    showTab(activeTab);
}

// Create set
function openCreateSet() { document.getElementById('createSetModal').classList.add('open'); }
function closeCreateSet() { document.getElementById('createSetModal').classList.remove('open'); document.getElementById('createSetError').textContent = ''; }

async function createSet() {
    var name = document.getElementById('setName').value.trim();
    if (!name) { document.getElementById('createSetError').textContent = 'Name is required'; return; }
    try {
        var r = await fetch('/api/sets/create', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name,
                description: document.getElementById('setDesc').value,
                target_lang: document.getElementById('setLang').value,
                is_public: document.getElementById('setPublic').checked
            })
        });
        var d = await r.json();
        if (d.error) { document.getElementById('createSetError').textContent = d.error; return; }
        closeCreateSet();
        document.getElementById('setName').value = '';
        document.getElementById('setDesc').value = '';
        loadMySets();
    } catch(e) { document.getElementById('createSetError').textContent = 'Error creating set'; }
}

// Delete set
async function deleteCurrentSet() {
    if (!confirm('Delete this set? This cannot be undone.')) return;
    try {
        await fetch('/api/sets/' + currentSetId + '/delete', { method: 'DELETE' });
        closeDetail();
    } catch(e) { console.error(e); }
}

// Toggle public/private
async function toggleSetPublic() {
    var newPublic = !currentSetData.is_public;
    try {
        await fetch('/api/sets/' + currentSetId + '/visibility', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ is_public: newPublic })
        });
        openSet(currentSetId); // Refresh
    } catch(e) { console.error(e); }
}

// Remove word from set
async function removeFromSet(setId, vocabId) {
    try {
        await fetch('/api/sets/' + setId + '/remove', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ vocab_id: vocabId })
        });
        openSet(setId); // Refresh
    } catch(e) { console.error(e); }
}

function escapeHtml(s) {
    return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function goPracticeThisSet() {
    if (!currentSetId) return;
    var lang = currentSetData && currentSetData.target_lang ? currentSetData.target_lang : '';
    var hash = '#flashcards?set=' + encodeURIComponent(currentSetId);
    if (lang) hash += '&lang=' + encodeURIComponent(lang);
    window.location.href = '/' + hash;
}

async function forkCurrentSet() {
    if (!currentSetId) return;
    var btn = document.getElementById('saveToLibraryBtn');
    if (!btn || btn.disabled) return;
    var originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Saving…';
    try {
        var r = await fetch('/api/sets/' + currentSetId + '/fork', { method: 'POST' });
        var d = await r.json();
        if (d.error) {
            btn.textContent = d.error;
            setTimeout(function(){ btn.disabled = false; btn.textContent = originalText; }, 2000);
            return;
        }
        var msg = 'Saved!';
        if (d.words_copied === 0 && d.words_existing > 0) {
            msg = 'Saved (' + d.words_existing + ' already in vocab)';
        } else if (d.words_existing > 0) {
            msg = 'Saved (+' + d.words_copied + ' new, ' + d.words_existing + ' already in vocab)';
        } else if (d.words_copied > 0) {
            msg = 'Saved (+' + d.words_copied + ' words)';
        }
        btn.textContent = msg;
        setTimeout(function(){
            activeTab = 'my-sets';
            openSet(d.new_set_id);
        }, 1100);
    } catch(e) {
        btn.textContent = 'Error - try again';
        setTimeout(function(){ btn.disabled = false; btn.textContent = originalText; }, 2000);
    }
}

// Add saved vocabulary to a set
function openAddWords() {
    if (!currentSetId || !currentSetData) return;
    addWordsState = { available: [], alreadyIds: new Set(), selected: new Set(), filter: '' };
    document.getElementById('addWordsSearch').value = '';
    document.getElementById('addWordsCounter').textContent = '0 selected';
    document.getElementById('addWordsCounter').classList.remove('has-selection');
    document.getElementById('addWordsConfirm').disabled = true;
    document.getElementById('addWordsConfirm').textContent = 'Add to set';
    document.getElementById('addWordsHint').textContent = 'Pick saved ' + (langNames[currentSetData.target_lang] || currentSetData.target_lang || '') + ' words for "' + currentSetData.name + '".';
    document.getElementById('addWordsList').innerHTML = '<div class="add-words-empty">Loading vocabulary…</div>';
    document.getElementById('addWordsModal').classList.add('open');

    Promise.all([
        fetch('/api/sets/' + currentSetId).then(function(r) { return r.json(); }),
        fetch('/api/vocab/list?lang=' + encodeURIComponent(currentSetData.target_lang || '')).then(function(r) { return r.json(); })
    ]).then(function(results) {
        var setData = results[0];
        var vocabData = results[1];
        addWordsState.alreadyIds = new Set((setData.words || []).map(function(w) { return w.id; }));
        addWordsState.available = vocabData.words || [];
        renderAddWordsList();
    }).catch(function(e) {
        console.error(e);
        document.getElementById('addWordsList').innerHTML = '<div class="add-words-empty">Could not load your vocabulary.</div>';
    });
}

function renderAddWordsList() {
    var list = document.getElementById('addWordsList');
    var filter = (addWordsState.filter || '').toLocaleLowerCase().trim();
    if (!addWordsState.available.length) {
        list.innerHTML = '<div class="add-words-empty">No saved vocabulary in this language yet. Save some words from the translator first.</div>';
        return;
    }
    var visible = addWordsState.available.filter(function(w) {
        if (!filter) return true;
        var hay = ((w.word || '') + ' ' + escapeHtml(w.meaning) + ' ' + (w.base_form || '')).toLocaleLowerCase();
        return hay.indexOf(filter) !== -1;
    });
    if (!visible.length) {
        list.innerHTML = '<div class="add-words-empty">No words match "' + escapeHtml(filter) + '".</div>';
        return;
    }
    list.innerHTML = visible.map(function(w) {
        var already = addWordsState.alreadyIds.has(w.id);
        var selected = addWordsState.selected.has(w.id);
        var classes = 'add-word-row';
        if (already) classes += ' is-already';
        else if (selected) classes += ' is-selected';
        var clickHandler = already ? '' : 'onclick="toggleAddWord(' + w.id + ')"';
        var label = already ? '<span class="add-word-already-label">already in set</span>' : '';
        return '<div class="' + classes + '" ' + clickHandler + '>' +
            '<div class="add-word-checkbox"></div>' +
            '<div class="add-word-info">' +
            '<div class="add-word-text">' + escapeHtml(w.word || '') + '</div>' +
            '<div class="add-word-meaning">' + escapeHtml(w.meaning || w.base_form || '') + '</div>' +
            '</div>' + label + '</div>';
    }).join('');
}

function toggleAddWord(vocabId) {
    if (addWordsState.alreadyIds.has(vocabId)) return;
    if (addWordsState.selected.has(vocabId)) addWordsState.selected.delete(vocabId);
    else addWordsState.selected.add(vocabId);
    renderAddWordsList();
    var n = addWordsState.selected.size;
    var counter = document.getElementById('addWordsCounter');
    counter.textContent = n + ' selected';
    counter.classList.toggle('has-selection', n > 0);
    document.getElementById('addWordsConfirm').disabled = n === 0;
}

function filterAddWords() {
    addWordsState.filter = document.getElementById('addWordsSearch').value;
    renderAddWordsList();
}

function closeAddWords() {
    document.getElementById('addWordsModal').classList.remove('open');
}

async function confirmAddWords() {
    var btn = document.getElementById('addWordsConfirm');
    var ids = Array.from(addWordsState.selected);
    if (!ids.length) return;
    btn.disabled = true;
    btn.textContent = 'Adding…';
    try {
        await Promise.all(ids.map(function(vid) {
            return fetch('/api/sets/' + currentSetId + '/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ vocab_id: vid })
            }).then(function(r) {
                if (!r.ok) throw new Error('Could not add word ' + vid);
                return r;
            });
        }));
        closeAddWords();
        openSet(currentSetId);
        loadMySets();
    } catch(e) {
        btn.disabled = false;
        btn.textContent = 'Add to set';
        showToast('Could not add some words. Please try again.');
    }
}

// Friends
function openAddFriend() {
    document.getElementById('addFriendModal').classList.add('open');
    setTimeout(function(){ document.getElementById('friendEmail').focus(); }, 0);
}
function closeAddFriend() { document.getElementById('addFriendModal').classList.remove('open'); document.getElementById('addFriendError').textContent = ''; }

function submitFriendOnEnter(event) {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    sendRequest();
}

async function sendRequest() {
    var email = document.getElementById('friendEmail').value.trim();
    var errEl = document.getElementById('addFriendError');
    var btn = document.querySelector('#addFriendModal .btn-primary');
    errEl.textContent = '';
    errEl.style.color = '';
    if (!email) { errEl.textContent = 'Email required'; return; }
    if (!btn) return;
    if (btn.disabled) return;
    btn.disabled = true;
    var originalText = btn.textContent;
    btn.textContent = 'Sending…';
    try {
        var r = await fetch('/api/friends/request', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ email: email })
        });
        var d = await r.json();
        if (d.error) {
            errEl.textContent = d.error;
            btn.disabled = false;
            btn.textContent = originalText;
            return;
        }
        errEl.style.color = 'var(--ivy)';
        errEl.textContent = 'Request sent to ' + email;
        btn.textContent = 'Sent';
        setTimeout(function(){
            closeAddFriend();
            document.getElementById('friendEmail').value = '';
            btn.disabled = false;
            btn.textContent = originalText;
            errEl.style.color = '';
            loadFriends();
        }, 1200);
    } catch(e) {
        errEl.textContent = 'Error sending request';
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

async function loadFriends() {
    try {
        var r = await fetch('/api/friends/list');
        var d = await r.json();
        if (d.error) { document.getElementById('friendsList').innerHTML = '<div class="empty-state"><h3>Log in required</h3></div>'; return; }

        var html = '';

        // Pending requests
        if (d.pending && d.pending.length > 0) {
            html += '<div class="pending-label">Pending requests</div>';
            html += d.pending.map(function(p) {
                return '<div class="friend-card">' +
                    '<div class="friend-avatar">' + escapeHtml(String(p.display_name || '').substring(0,2).toUpperCase()) + '</div>' +
                    '<div class="friend-info"><div class="friend-name">' + escapeHtml(p.display_name) + '</div><div class="friend-email">' + escapeHtml(p.email) + '</div></div>' +
                    '<div class="friend-actions">' +
                    '<button class="btn btn-primary btn-sm" onclick="acceptFriend(' + p.friendship_id + ')">Accept</button>' +
                    '<button class="btn btn-sm" onclick="rejectFriend(' + p.friendship_id + ')">Decline</button>' +
                    '</div></div>';
            }).join('');
        }

        // Accepted friends
        if (d.friends && d.friends.length > 0) {
            html += d.friends.map(function(f) {
                var friendName = String(f.display_name || 'Friend');
                var safeName = escapeHtml(friendName.replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
                return '<div class="friend-card">' +
                    '<div class="friend-avatar">' + escapeHtml(String(f.display_name || '').substring(0,2).toUpperCase()) + '</div>' +
                    '<div class="friend-info"><div class="friend-name">' + escapeHtml(f.display_name) + '</div><div class="friend-email">' + escapeHtml(f.email) + '</div></div>' +
                    '<div class="friend-actions">' +
                    '<button class="btn btn-sm" onclick="viewFriendSets(' + f.friend_id + ',\'' + safeName + '\')">View sets</button>' +
                    '<button class="btn btn-danger btn-sm" onclick="removeFriend(' + f.friendship_id + ',\'' + safeName + '\')">Remove</button>' +
                    '</div>' +
                    '</div>';
            }).join('');
        } else if (!d.pending || d.pending.length === 0) {
            html = '<div class="empty-state"><h3>No friends yet</h3><p>Add friends by email to see their public flashcard sets</p></div>';
        }

        document.getElementById('friendsList').innerHTML = html;
    } catch(e) { console.error(e); }
}

async function acceptFriend(id) {
    await fetch('/api/friends/accept/' + id, { method: 'POST' });
    loadFriends();
}

async function rejectFriend(id) {
    await fetch('/api/friends/reject/' + id, { method: 'POST' });
    loadFriends();
}

async function removeFriend(id, name) {
    if (!confirm('Remove ' + name + ' from your friends?')) return;
    try {
        var r = await fetch('/api/friends/remove/' + id, { method: 'POST' });
        var d = await r.json();
        if (d.error) { showToast(d.error); return; }
        loadFriends();
    } catch(e) {
        showToast('Could not remove friend. Please try again.');
    }
}

async function viewFriendSets(friendId, friendName) {
    try {
        var r = await fetch('/api/friends/' + friendId + '/sets');
        var d = await r.json();
        if (d.error) { showToast(d.error); return; }

        document.querySelectorAll('.section').forEach(function(s) { s.classList.remove('active'); s.style.display = 'none'; });
        document.querySelector('.tabs').style.display = 'none';

        var sec = document.getElementById('sec-detail');
        document.getElementById('detailTitle').textContent = friendName + "'s public sets";
        document.getElementById('detailDesc').textContent = '';
        document.getElementById('detailMeta').innerHTML = '<span class="set-badge badge-count">' + d.sets.length + (d.sets.length === 1 ? ' public set' : ' public sets') + '</span>';
        document.getElementById('studyBtn').style.display = 'none';
        document.getElementById('saveToLibraryBtn').style.display = 'none';
        document.getElementById('addWordsBtn').style.display = 'none';
        document.getElementById('togglePublicBtn').style.display = 'none';
        document.getElementById('deleteSetBtn').style.display = 'none';

        if (d.sets.length === 0) {
            document.getElementById('detailWords').innerHTML = '<div class="empty-state"><p>' + escapeHtml(friendName) + ' has no public sets yet</p></div>';
        } else {
            document.getElementById('detailWords').innerHTML = '<div class="set-grid">' + d.sets.map(function(s) {
                var badges = '<span class="set-badge badge-count">' + wordCount(s.word_count) + '</span>';
                if (s.target_lang) badges += '<span class="set-badge badge-lang">' + (langNames[s.target_lang] || s.target_lang) + '</span>';
                return '<div class="set-card" role="button" tabindex="0" onclick="openSet(' + s.id + ')" onkeydown="onCardKey(event, ' + s.id + ')"><div class="set-name">' + escapeHtml(s.name) + '</div>' +
                    (s.description ? '<div class="set-desc">' + escapeHtml(s.description) + '</div>' : '') +
                    '<div class="set-meta">' + badges + '</div></div>';
            }).join('') + '</div>';
        }
        sec.style.display = 'block';
    } catch(e) { console.error(e); }
}

function wordCount(n) {
    n = n || 0;
    return n + (n === 1 ? ' word' : ' words');
}

// Open a set card with Enter or Space, like a button.
function onCardKey(e, setId) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSet(setId); }
}

// Short message at the bottom of the screen, instead of a browser alert.
function showToast(message) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(function() { el.classList.remove('show'); }, 4000);
}

// Match the theme chosen on the translator page.
if (document.body.getAttribute('data-theme') === 'light') {
    var siteLogo = document.getElementById('siteLogo');
    if (siteLogo) siteLogo.src = '/static/logo-light.png';
}

// Init
var initialTab = (window.location.hash || '').replace('#', '');
if (['my-sets', 'browse', 'friends'].indexOf(initialTab) !== -1) {
    showTab(initialTab);
} else {
    loadMySets();
}
