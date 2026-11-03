/*
 * motion.js - Ivy's micro-interactions (the moves that need a little script).
 * Loaded after ivy.js. Styles live in /static/css/motion.css.
 */
(function () {
    'use strict';

    var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Restart a one-shot CSS animation class on an element.
    function replay(el, className) {
        if (!el) return;
        el.classList.remove(className);
        void el.offsetWidth; // let the browser see the class come off before it goes back on
        el.classList.add(className);
        el.addEventListener('animationend', function done(e) {
            if (e.target !== el) return;
            el.classList.remove(className);
            el.removeEventListener('animationend', done);
        });
    }
    window.ivyReplay = replay;

    // ── Mode tabs: one pill that slides under the active tab ──────────────
    var tabs = document.querySelector('.mode-tabs');
    var indicator = null;

    function placeIndicator(animate) {
        if (!tabs || !indicator) return;
        var active = tabs.querySelector('.mode-tab.active');
        if (!active) return;
        if (!animate) indicator.classList.add('no-anim');
        indicator.style.width = active.offsetWidth + 'px';
        indicator.style.setProperty('--x', active.offsetLeft + 'px');
        if (!animate) {
            void indicator.offsetWidth;
            indicator.classList.remove('no-anim');
        }
    }

    if (tabs) {
        indicator = document.createElement('span');
        indicator.className = 'mode-tab-indicator';
        indicator.setAttribute('aria-hidden', 'true');
        tabs.appendChild(indicator);
        tabs.classList.add('has-indicator');
        placeIndicator(false);
        window.addEventListener('resize', function () { placeIndicator(false); });
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { placeIndicator(false); });
    }

    // ── Switching modes: slide the pill, let the new view rise in ─────────
    if (typeof window.setMode === 'function') {
        var originalSetMode = window.setMode;
        window.setMode = function (mode) {
            var before = typeof currentMode !== 'undefined' ? currentMode : null;
            originalSetMode.apply(this, arguments);
            placeIndicator(true);
            if (before === mode) return;
            var view = typeof getModeView === 'function' ? getModeView(mode) : null;
            // Translate and Compare share one view; only the panels change.
            var sameView = (before === 'translate' || before === 'compare') && (mode === 'translate' || mode === 'compare');
            replay(sameView ? document.getElementById('translatorGrid') : view, 'view-enter');
        };
    }

    // ── Swap languages: the arrows turn, the names trade places ───────────
    var swapBtn = document.querySelector('.swap-btn');
    if (swapBtn && !swapBtn.querySelector('.swap-glyph')) {
        swapBtn.innerHTML = '<span class="swap-glyph" aria-hidden="true">' + swapBtn.innerHTML + '</span>';
    }
    if (typeof window.swapLangs === 'function') {
        var originalSwap = window.swapLangs;
        window.swapLangs = function () {
            originalSwap.apply(this, arguments);
            if (swapBtn) swapBtn.classList.toggle('is-turned');
            var src = document.getElementById('srcLang');
            var tgt = document.getElementById('tgtLang');
            if (src) { src.style.setProperty('--from', '6px'); replay(src, 'lang-swapped'); }
            if (tgt) { tgt.style.setProperty('--from', '-6px'); replay(tgt, 'lang-swapped'); }
        };
    }

    // ── Register chips: the picked chip settles in ────────────────────────
    if (typeof window.setStyle === 'function') {
        var originalSetStyle = window.setStyle;
        window.setStyle = function (el) {
            var wasActive = el && el.classList.contains('active');
            originalSetStyle.apply(this, arguments);
            if (!wasActive) replay(el, 'just-picked');
        };
    }

    // ── Theme: the icon turns while the colours change ────────────────────
    if (typeof window.toggleTheme === 'function') {
        var originalToggleTheme = window.toggleTheme;
        var themeBtn = document.getElementById('themeToggle');
        window.toggleTheme = function () {
            originalToggleTheme.apply(this, arguments);
            if (!themeBtn || reduceMotion) return;
            themeBtn.classList.add('is-turning');
            setTimeout(function () { themeBtn.classList.remove('is-turning'); }, 420);
        };
    }

    // ── Stories: a new story arrives in reading order ─────────────────────
    // renderStoryContent also re-runs when word analysis finishes; only a
    // different story gets the entrance.
    if (typeof window.renderStoryContent === 'function') {
        var originalRenderStory = window.renderStoryContent;
        var lastStoryKey = '';
        window.renderStoryContent = function (story) {
            originalRenderStory.apply(this, arguments);
            var key = story ? (story.title || '') + '|' + String(story.story_text || '').length : '';
            if (!key || key === lastStoryKey) { lastStoryKey = key; return; }
            lastStoryKey = key;
            ['storyTitle', 'storyText', 'storySummary', 'storyQuestions', 'storyVocab'].forEach(function (id, i) {
                var el = document.getElementById(id);
                if (!el) return;
                el.style.setProperty('--i', i);
                replay(el, 'story-arrive');
            });
        };
    }

    // ── Numbers that count to their new value (tone percentages, scores) ──
    window.ivyCountTo = function (el, to, suffix) {
        if (!el) return;
        suffix = suffix || '';
        var from = parseInt(el.dataset.value || '0', 10) || 0;
        el.dataset.value = String(to);
        if (reduceMotion || from === to) { el.textContent = to + suffix; return; }
        var start = null;
        var duration = 600;
        function frame(now) {
            if (start === null) start = now;
            var t = Math.min(1, (now - start) / duration);
            var eased = 1 - Math.pow(1 - t, 4);
            el.textContent = Math.round(from + (to - from) * eased) + suffix;
            if (t < 1) requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    };
})();
