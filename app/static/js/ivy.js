const langNames={tr:'Turkish',ru:'Russian',de:'German',en:'English'};
let currentStyle='formal',currentMode='translate',translateTimer=null,detectTimer=null;
let radarChart=null,isTranslating=false,lastTranslation='',lastWordData=[],lastTranslationSource='';
let translateRequestId=0,compareRequestId=0,translateAbortController=null,compareAbortController=null;
let currentUser=null,flashcards=[],fcIndex=0;
let currentFlashcardLang='tr';
let currentFlashcardSetId=null;
let availableFlashcardSets=[];
let currentStory=null,isGeneratingStory=false;
let storyReaderOpen=false;
let storyFactTimer=null,storyFactIndex=0;
let savedVocabKeys=new Set(),savedVocabLang='';
let currentWordAudio=null,currentWordAudioUrl='';
const storyWordAudioCache=new Map();
const storyWordAudioPending=new Map();
let storyWordAudioToken=0;
let activeWordSourceText='',activeWordTranslationText='',activeWordSourceLang='en',activeWordTargetLang='tr',activeWordStyle='neutral';
let currentStoryAudioUrl='';
let currentStoryNarrationB64='';
let karaokeEnabled=false,karaokeRaf=null,karaokeFetchToken=0,karaokeLastSpokenIndex=-1,karaokeDataPromise=null;
let karaokeWordSpans=[];
let vocabCounts={tr:0,de:0,ru:0,en:0};
const PERSONALIZE_THRESHOLD=10;
const $=id=>document.getElementById(id);
const logoSources={dark:'/static/logo-dark.png',light:'/static/logo-light.png'};
const markLogoSources={dark:'/static/logo-mark-dark-128.png',light:'/static/logo-mark-128.png'};
const speakerIconSources={dark:'/static/speaker-icon-dark-128.png',light:'/static/speaker-icon-light-128.png'};
const defaultOutputHint='Tap or hover a translated word to see its meaning and grammar, and save it to your vocabulary.';
const loadingOutputHint='Translating with word-level analysis…';
const errorOutputHint='Check your connection or try again in a moment.';
const storyFunFacts=[
    'Fun fact: Reading just above your level is called comprehensible input.',
    'Fun fact: CEFR A2 stories usually recycle common daily-life verbs.',
    'Fun fact: Seeing a word in context helps memory more than isolated lists.',
    'Fun fact: Short stories are great for noticing grammar patterns naturally.',
    'Fun fact: Rereading the same text can improve reading speed and confidence.',
    'Fun fact: Saving 5 useful words after reading is better than saving 30 random ones.'
];
const surpriseThemes={
    A1:['buying bread','a lost cat','my first bus ride','a sunny picnic','meeting a new neighbor','a small birthday party'],
    A2:['a rainy market day','finding a forgotten letter','a friendly cafe mistake','getting ready for a school trip','helping a neighbor move','a weekend at the train station'],
    B1:['solving a small mystery at school','a festival volunteer shift','a disagreement between friends','getting lost in an old neighborhood','starting a new hobby club','an unexpected guest at dinner'],
    B2:['a student radio interview goes wrong','planning a community garden','a debate before a local festival','a difficult choice during an internship','two friends opening a tiny bookshop','a travel delay that changes the day'],
    C1:['a journalist investigating a quiet rumor','a family argument during a historic renovation','a musician deciding whether to leave town','a neighborhood adapting to sudden change','an ethical dilemma at a research lab','a tense reunion after many years']
};

function applyTheme(theme){
    var resolved=theme==='light'?'light':'dark';
    document.body.setAttribute('data-theme',resolved);
    var toggle=$('themeToggle');
    var icon=$('themeToggleIcon');
    var logo=$('siteLogo');
    var ivyWhyLogo=$('ivyWhyLogo');
    var ivyPanelLogo=$('ivyPanelLogo');
    var practiceEmptyLogo=$('practiceEmptyLogo');
    var speakerIcon=$('speakerIcon');
    var sunIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"></circle><path d="M12 2.5v2.5M12 19v2.5M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2.5 12H5M19 12h2.5M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"></path></svg>';
    var moonIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.2A8.5 8.5 0 0 1 9.8 4 9 9 0 1 0 20 14.2z"></path></svg>';
    if(toggle)toggle.setAttribute('aria-label','Switch to '+(resolved==='dark'?'light':'dark')+' mode');
    if(icon)icon.innerHTML=resolved==='dark'?sunIcon:moonIcon;
    if(logo)logo.src=resolved==='light'?logoSources.light:logoSources.dark;
    if(ivyWhyLogo)ivyWhyLogo.src=resolved==='light'?markLogoSources.light:markLogoSources.dark;
    if(ivyPanelLogo)ivyPanelLogo.src=resolved==='light'?markLogoSources.light:markLogoSources.dark;
    if(practiceEmptyLogo)practiceEmptyLogo.src=resolved==='light'?markLogoSources.light:markLogoSources.dark;
    if(speakerIcon)speakerIcon.src=resolved==='light'?speakerIconSources.light:speakerIconSources.dark;
}

function initTheme(){
    var saved=localStorage.getItem('ivy-theme');
    applyTheme(saved||'dark');
}

function toggleTheme(){
    var next=document.body.getAttribute('data-theme')==='light'?'dark':'light';
    applyTheme(next);
    localStorage.setItem('ivy-theme',next);
}

function setOutputEmpty(title,hint){
    outputArea.classList.remove('is-stale','is-failed','is-arriving');
    outputArea.innerHTML='';
    outputArea.dataset.hint=hint||defaultOutputHint;
    outputArea.classList.add('empty');
    outputArea.style.color='';
}

// A quiet line under the output, e.g. when Gemini's daily quota is used up.
function showAiNotice(message){
    var el=$('aiNotice');
    if(!el)return;
    var text=String(message||'');
    if(el.textContent===text&&el.classList.contains('visible')===!!text)return;
    el.textContent=text;
    el.classList.toggle('visible',!!text);
}

function setCompareLoading(){
    $('cmpFormal').textContent='Preparing formal version…';
    $('cmpNeutral').textContent='Preparing neutral version…';
    $('cmpCasual').textContent='Preparing casual version…';
    document.querySelectorAll('#compareResults .compare-text').forEach(function(el){el.classList.add('is-waiting');});
}

function escapeHtml(value){
    return String(value||'')
        .replace(/&/g,'&amp;')
        .replace(/</g,'&lt;')
        .replace(/>/g,'&gt;')
        .replace(/"/g,'&quot;')
        .replace(/'/g,'&#39;');
}

function safeJsonArray(value){
    try{
        var parsed=JSON.parse(value||'[]');
        return Array.isArray(parsed)?parsed:[];
    }catch(e){
        return [];
    }
}

function langName(code){
    return langNames[code]||code;
}

async function refreshVocabCounts(){
    if(currentUser){
        try{
            var r=await fetch('/api/vocab/count');
            var d=await r.json();
            vocabCounts=d.counts||vocabCounts;
        }catch(e){}
    }else{
        vocabCounts={tr:0,de:0,ru:0,en:0};
    }
    applyPersonalizeState();
}

function applyPersonalizeState(){
    var el=$('storyPersonalize');
    if(!el)return;
    var lang=$('storyTargetLang')?$('storyTargetLang').value:'tr';
    var count=vocabCounts[lang]||0;
    var hint=$('storyPersonalizeHint');

    if(!currentUser){
        el.classList.add('is-disabled');
        el.classList.remove('is-on');
        el.setAttribute('aria-checked','false');
        if(hint)hint.textContent='Log in and save vocabulary to personalize';
        return;
    }

    if(count<PERSONALIZE_THRESHOLD){
        var remaining=PERSONALIZE_THRESHOLD-count;
        el.classList.add('is-disabled');
        el.classList.remove('is-on');
        el.setAttribute('aria-checked','false');
        if(hint)hint.textContent='Save '+remaining+' more '+langName(lang)+' word'+(remaining===1?'':'s')+' to enable';
        return;
    }

    el.classList.remove('is-disabled');
    var prefKey='ivy-personalize-'+lang;
    var pref=localStorage.getItem(prefKey);
    var on=pref===null?true:pref==='1';
    el.classList.toggle('is-on',on);
    el.setAttribute('aria-checked',on?'true':'false');
    if(hint)hint.textContent=count+' '+langName(lang)+' word'+(count===1?'':'s')+' saved; stories adapt to what you know';
}

function togglePersonalize(){
    var el=$('storyPersonalize');
    if(!el||el.classList.contains('is-disabled'))return;
    var lang=$('storyTargetLang')?$('storyTargetLang').value:'tr';
    var prefKey='ivy-personalize-'+lang;
    var nowOn=!el.classList.contains('is-on');
    localStorage.setItem(prefKey,nowOn?'1':'0');
    applyPersonalizeState();
}

function isPersonalizeOn(){
    var el=$('storyPersonalize');
    return !!(el&&el.classList.contains('is-on')&&!el.classList.contains('is-disabled'));
}

function vocabKey(word,lang){
    return String(lang||'')+'|'+String(word||'').trim().toLocaleLowerCase();
}

async function refreshSavedVocabState(lang){
    savedVocabKeys=new Set();
    savedVocabLang=lang||'';
    if(!currentUser||!lang)return;
    try{
        var r=await fetch('/api/vocab/list?lang='+encodeURIComponent(lang));
        var d=await r.json();
        (d.words||[]).forEach(function(item){
            savedVocabKeys.add(vocabKey(item.word,lang));
        });
    }catch(e){}
}

function markFocusVocabularySaved(){
    if(!currentStory||!currentStory.focus_vocabulary)return;
    document.querySelectorAll('.story-vocab-save').forEach(function(btn){
        var index=parseInt(btn.dataset.index||'-1',10);
        var item=currentStory.focus_vocabulary[index];
        if(item&&savedVocabKeys.has(vocabKey(item.word,currentStory.target_lang))){
            btn.innerHTML='&#10003;';
            btn.classList.add('saved');
        }
    });
}

function focusMeaningForWord(word){
    if(!currentStory||!currentStory.focus_vocabulary)return '';
    var key=String(word||'').toLocaleLowerCase();
    var found=currentStory.focus_vocabulary.find(function(item){
        return String(item.word||'').toLocaleLowerCase()===key;
    });
    return found?found.meaning||'':'';
}

function sentenceForWord(text,word){
    var source=String(text||'').trim();
    var needle=String(word||'').trim();
    if(!source||!needle)return source;
    var sentences=source.match(/[^.!?。！？]+[.!?。！？]?/g)||[source];
    var lowerNeedle=needle.toLocaleLowerCase();
    for(var i=0;i<sentences.length;i++){
        if(sentences[i].toLocaleLowerCase().indexOf(lowerNeedle)!==-1){
            return sentences[i].trim();
        }
    }
    return source;
}

function saveStoryPreferences(){
    var lang=$('storyTargetLang')?$('storyTargetLang').value:'tr';
    var level=$('storyLevel')?$('storyLevel').value:'A2';
    localStorage.setItem('ivy-story-target-lang',lang);
    localStorage.setItem('ivy-story-cefr-level',level);
    if($('storyMeta')&&!currentStory){
        $('storyMeta').innerHTML=
            '<span class="story-badge level">'+escapeHtml(level)+'</span>'+
            '<span class="story-badge theme">'+escapeHtml($('storyTheme').value||'daily life')+'</span>'+
            '<span class="story-badge length">'+escapeHtml($('storyLength').value||'short')+'</span>'+
            '<span class="story-badge style">'+escapeHtml($('storyStyle').value||'neutral')+'</span>';
    }
}

function initStoryPreferences(){
    if(!$('storyTargetLang'))return;
    var savedLang=localStorage.getItem('ivy-story-target-lang')||$('tgtLang').value||'tr';
    var savedLevel=localStorage.getItem('ivy-story-cefr-level')||'A2';
    $('storyTargetLang').value=savedLang;
    $('storyLevel').value=savedLevel;
    saveStoryPreferences();
}

function surpriseStoryTheme(){
    var level=($('storyLevel')&&$('storyLevel').value)||'A2';
    var options=surpriseThemes[level]||surpriseThemes.A2;
    var choice=options[Math.floor(Math.random()*options.length)];
    $('storyTheme').value=choice;
    saveStoryPreferences();
    $('storyStatus').textContent='Surprise theme selected: '+choice+'.';
}

function openStoryReader(){
    storyReaderOpen=true;
    $('storyShell').classList.add('reader-open');
    updateStoryShellHeight();
    requestAnimationFrame(syncModeStageHeight);
}

function updateStoryShellHeight(){
    var shell=$('storyShell');
    if(!shell)return;
    var active=storyReaderOpen?$('storyReaderView'):$('storySetupView');
    var nextHeight=active?Math.max(active.scrollHeight,620):620;
    shell.style.minHeight=nextHeight+'px';
}

function renderFlashcardFilters(languages){
    var filters=$('fcFilters');
    if(!filters)return;
    if(!languages||languages.length===0){
        filters.innerHTML='';
        filters.style.display='none';
        return;
    }
    filters.style.display='flex';
    filters.innerHTML=languages.map(function(lang){
        var active=lang===currentFlashcardLang?' active':'';
        return '<button class="flashcard-filter'+active+'" data-lang="'+lang+'" onclick="setFlashcardLang(this,\''+lang+'\')">'+(langNames[lang]||lang)+'</button>';
    }).join('');
}

async function getFlashcardLanguages(preferredLang){
    if(!currentUser)return [];
    try{
        var r=await fetch('/api/vocab/stats');
        var stats=await r.json();
        var languages=Object.keys(stats.by_language||{}).filter(function(lang){
            return (stats.by_language[lang]||0)>0;
        });
        if(preferredLang&&languages.indexOf(preferredLang)===-1&&languages.length>0){
            currentFlashcardLang=languages[0];
        }
        return languages;
    }catch(e){
        console.error(e);
        return [];
    }
}

// Check restyle mode
function checkRestyleMode(){
    const same=$('srcLang').value===$('tgtLang').value;
    $('restyleBadge').classList.toggle('visible',same);
    $('inputArea').placeholder=same?'Type text to restyle…':'Start typing to translate…';
}
function rescheduleForCurrentMode(){
    if($('inputArea').value.trim().length<=2)return;
    if(currentMode==='compare')scheduleCompare();
    else scheduleTranslation();
}
$('srcLang').addEventListener('change',()=>{checkRestyleMode();rescheduleForCurrentMode();});
$('tgtLang').addEventListener('change',()=>{checkRestyleMode();rescheduleForCurrentMode();});

// Auth
async function checkAuth(){try{const r=await fetch('/api/auth/me');const d=await r.json();if(d.user){currentUser=d.user;}updateAuthUI();loadSavedStories();refreshVocabCounts();if(currentMode==='practice')initPracticeMode();if(currentMode==='flashcards')loadFlashcards(currentFlashcardLang);}catch(e){loadSavedStories();refreshVocabCounts();if(currentMode==='practice')initPracticeMode();}}
function updateAuthUI(){
    const btn=$('avatarBtn');
    if(currentUser){btn.textContent=currentUser.display_name.substring(0,2).toUpperCase();btn.classList.add('logged-in');$('dropdownHeader').innerHTML=`<div class="dropdown-name">${escapeHtml(currentUser.display_name)}</div><div class="dropdown-email">${escapeHtml(currentUser.email)}</div>`;$('menuLogin').style.display='none';$('menuLogout').style.display='flex';}
    var shelfNote=$('savedStoriesSubtle');
    if(shelfNote)shelfNote.textContent=currentUser?'Your reading shelf':'Log in to keep a personal reading shelf';
    else{btn.textContent='Guest';btn.classList.remove('logged-in');$('dropdownHeader').innerHTML='<div class="dropdown-name">Guest</div><div class="dropdown-email">Not logged in</div>';$('menuLogin').style.display='flex';$('menuLogout').style.display='none';}
}
function openAuth(){$('authModal').classList.add('open');showLogin();}
function closeAuth(){$('authModal').classList.remove('open');}
function showLogin(){$('loginForm').style.display='block';$('signupForm').style.display='none';}
function showSignup(){$('loginForm').style.display='none';$('signupForm').style.display='block';}
async function doLogin(){const e=$('loginEmail').value,p=$('loginPass').value;try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});const d=await r.json();if(d.error){$('loginError').textContent=d.error;$('loginError').classList.add('visible');}else{currentUser=d.user;updateAuthUI();loadSavedStories();refreshVocabCounts();if(currentMode==='practice')initPracticeMode();if(currentMode==='flashcards')loadFlashcards(currentFlashcardLang);closeAuth();}}catch(e){$('loginError').textContent='Connection error';$('loginError').classList.add('visible');}}
async function doSignup(){const n=$('signupName').value,e=$('signupEmail').value,p=$('signupPass').value;try{const r=await fetch('/api/auth/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,email:e,password:p})});const d=await r.json();if(d.error){$('signupError').textContent=d.error;$('signupError').classList.add('visible');}else{currentUser=d.user;updateAuthUI();loadSavedStories();refreshVocabCounts();if(currentMode==='practice')initPracticeMode();if(currentMode==='flashcards')loadFlashcards(currentFlashcardLang);closeAuth();}}catch(e){$('signupError').textContent='Connection error';$('signupError').classList.add('visible');}}
function submitAuthOnEnter(event,mode){
    if(event.key!=='Enter')return;
    event.preventDefault();
    if(mode==='signup')doSignup();
    else doLogin();
}
async function doLogout(){await fetch('/api/auth/logout',{method:'POST'});currentUser=null;currentFlashcardSetId=null;availableFlashcardSets=[];updateAuthUI();loadSavedStories();refreshVocabCounts();if(currentMode==='practice')initPracticeMode();if(currentMode==='flashcards')loadFlashcards(currentFlashcardLang);closeDropdown();}
function toggleUserMenu(){var open=$('userDropdown').classList.toggle('open');$('avatarBtn').setAttribute('aria-expanded',open?'true':'false');}
function closeDropdown(){$('userDropdown').classList.remove('open');$('avatarBtn').setAttribute('aria-expanded','false');}
document.addEventListener('click',e=>{if(!e.target.closest('.avatar-btn')&&!e.target.closest('.user-dropdown'))closeDropdown();});

// Vocab
async function openVocab(){closeDropdown();$('vocabPanel').classList.add('open');await loadVocab();}
function closeVocab(){$('vocabPanel').classList.remove('open');}
async function loadVocab(lang=''){
    if(!currentUser){$('vocabList').innerHTML='<div class="vocab-empty">Log in to see your vocabulary</div>';return;}
    try{const url=lang?'/api/vocab/list?lang='+lang:'/api/vocab/list';const r=await fetch(url);const d=await r.json();
    const sr=await fetch('/api/vocab/stats');const stats=await sr.json();
    $('vocabStats').innerHTML='<div class="stat-box"><div class="stat-num">'+stats.total+'</div><div class="stat-label">Words</div></div>'+Object.entries(stats.by_language||{}).map(function(entry){return'<div class="stat-box"><div class="stat-num">'+entry[1]+'</div><div class="stat-label">'+(langNames[entry[0]]||entry[0])+'</div></div>';}).join('');
    if(d.words.length===0){$('vocabList').innerHTML='<div class="vocab-empty">No words saved yet</div>';return;}
    $('vocabList').innerHTML=d.words.map(function(w){var tags='<span class="vocab-tag tag-pos">'+escapeHtml(w.pos)+'</span>';if(w.grammatical_case)tags+='<span class="vocab-tag tag-case">'+escapeHtml(w.grammatical_case)+'</span>';if(w.difficulty)tags+='<span class="vocab-tag tooltip-cefr cefr-'+escapeHtml(w.difficulty)+'">'+escapeHtml(w.difficulty)+'</span>';return'<div class="vocab-card"><div style="display:flex;justify-content:space-between;align-items:flex-start;"><div><div class="vocab-word">'+escapeHtml(w.word)+'</div><div class="vocab-meaning">'+escapeHtml(w.meaning)+'</div></div><button class="vocab-delete" onclick="deleteVocab('+w.id+')">&times;</button></div><div class="vocab-meta">'+tags+'</div>'+(w.sentence?'<div class="vocab-sentence">'+escapeHtml(w.sentence)+'</div>':'')+'</div>';}).join('');
    }catch(e){console.error(e);}
}
function filterVocab(el,lang){document.querySelectorAll('.filter-chip').forEach(function(c){c.classList.remove('active');});el.classList.add('active');loadVocab(lang);}
async function deleteVocab(id){await fetch('/api/vocab/delete/'+id,{method:'DELETE'});loadVocab();}

// Save word
async function saveWord(event,index){
    event.stopPropagation();var btn=event.target;if(btn.classList.contains('saved'))return;
    if(!currentUser){openAuth();return;}
    var w=lastWordData[index];
    if(isPureWordPunct(w.word)){btn.textContent='Skipped';return;}
    var cleanWord=stripTrailingPunct(w.word)||w.word;
    var cleanBase=stripTrailingPunct(w.base_form||w.word)||cleanWord;
    var exampleSentence=(currentMode==='stories'&&currentStory)?sentenceForWord(currentStory.story_text,w.word):activeWordSourceText;
    var data={word:cleanWord,meaning:w.meaning||focusMeaningForWord(w.word),pos:normalizeDisplayPos(w.pos,w.word),"case":w["case"],gender:w.gender,base_form:cleanBase,difficulty:w.difficulty,sentence:exampleSentence,translation:activeWordTranslationText,source_lang:activeWordSourceLang,target_lang:activeWordTargetLang,style:activeWordStyle};
    try{await fetch('/api/vocab/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});btn.textContent='Saved!';btn.classList.add('saved');refreshVocabCounts();}catch(e){btn.textContent='Error';}
}

// Practice
let practiceItems=[];
let practiceIndex=0;
let practiceCorrect=0;
let practiceWrong=0;
let practiceState='setup';

async function initPracticeMode(){
    var langSelect=$('practiceLang');
    if(langSelect){
        if(currentStory&&currentStory.target_lang)langSelect.value=currentStory.target_lang;
        else langSelect.value=$('tgtLang').value||langSelect.value||'tr';
    }
    if(!currentUser){
        showPracticeView('empty');
        setPracticeEmptyState(
            'Log in to practice',
            'Log in and save a story or two. Ivy turns your saved reading into fill-in-the-blank practice.',
            'Log in',
            function(){openAuth();}
        );
        return;
    }
    await populatePracticeStorySources();
    showPracticeView('setup');
}

function showPracticeView(state){
    practiceState=state;
    var setup=$('practiceSetup'),empty=$('practiceEmpty'),quiz=$('practiceQuiz'),results=$('practiceResults');
    if(setup)setup.style.display=state==='setup'?'block':'none';
    if(empty)empty.style.display=state==='empty'?'block':'none';
    if(quiz)quiz.style.display=state==='quiz'?'block':'none';
    if(results)results.style.display=state==='results'?'block':'none';
    requestAnimationFrame(syncModeStageHeight);
}

function setPracticeEmptyState(title,message,buttonText,onClick){
    var empty=$('practiceEmpty');
    if(!empty)return;
    var h=empty.querySelector('h3');
    var p=empty.querySelector('p');
    var btn=empty.querySelector('button');
    if(h)h.textContent=title;
    if(p)p.textContent=message;
    if(btn){
        btn.textContent=buttonText;
        btn.onclick=onClick;
    }
}

async function onPracticeLangChange(){
    await populatePracticeStorySources();
}

async function populatePracticeStorySources(){
    var lang=$('practiceLang')?$('practiceLang').value:'tr';
    var sourceSelect=$('practiceSource');
    if(!sourceSelect)return;
    sourceSelect.innerHTML='<option value="all">All saved stories</option>';
    if(!currentUser)return;
    try{
        var r=await fetch('/api/stories/list?lang='+encodeURIComponent(lang));
        var d=await r.json();
        var stories=d.stories||[];
        stories.forEach(function(story){
            var opt=document.createElement('option');
            opt.value=story.id;
            var title=story.title||'Untitled story';
            if(title.length>58)title=title.slice(0,55)+'…';
            opt.textContent=title;
            sourceSelect.appendChild(opt);
        });
    }catch(e){}
}

async function startPracticeQuiz(){
    if(!currentUser){
        showPracticeView('empty');
        setPracticeEmptyState('Log in to practice','Log in and save a story or two. Ivy turns your saved reading into fill-in-the-blank practice.','Log in',function(){openAuth();});
        return;
    }
    var startBtn=$('practiceStartBtn');
    var statusEl=$('practiceStatus');
    if(startBtn)startBtn.disabled=true;
    if(statusEl){
        statusEl.classList.remove('error');
        statusEl.textContent='Building practice and translating sentences…';
    }
    var payload={
        target_lang:$('practiceLang').value,
        cefr_level:$('practiceLevel').value||null,
        limit:parseInt($('practiceLength').value,10)||10
    };
    var sourceVal=$('practiceSource').value;
    if(sourceVal&&sourceVal!=='all')payload.story_id=parseInt(sourceVal,10);
    try{
        var r=await fetch('/api/practice/build',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify(payload)
        });
        var d=await r.json();
        if(d.error)throw new Error(d.error);
        practiceItems=d.items||[];
        if(!practiceItems.length){
            showPracticeView('empty');
            setPracticeEmptyState(
                'No practice material yet',
                'Generate and save a story in this language, then Ivy can turn its words into cloze questions.',
                'Generate a story',
                function(){setMode('stories');}
            );
            return;
        }
        practiceIndex=0;
        practiceCorrect=0;
        practiceWrong=0;
        $('practiceCorrectCount').textContent='0';
        $('practiceWrongCount').textContent='0';
        if(statusEl)statusEl.textContent='';
        showPracticeView('quiz');
        renderPracticeItem();
    }catch(e){
        if(statusEl){
            statusEl.classList.add('error');
            statusEl.textContent=e.message||'Could not build practice quiz.';
        }
    }finally{
        if(startBtn)startBtn.disabled=false;
    }
}

function renderPracticeItem(){
    var item=practiceItems[practiceIndex];
    if(!item)return;
    var pct=(practiceIndex/practiceItems.length)*100;
    $('practiceProgressFill').style.width=pct+'%';
    $('practiceProgressText').textContent=(practiceIndex+1)+' of '+practiceItems.length;
    $('practiceItemSource').textContent='From: '+(item.story_title||'your stories');
    var blankLength=Math.max(String(item.answer||'').length,6);
    $('practiceSentence').innerHTML=escapeHtml(item.sentence||'').replace(/___/,'<span class="practice-blank" id="practiceBlank">'+Array(blankLength+1).join('_')+'</span>');
    $('practiceTranslation').innerHTML=renderPracticeTranslation(item.translation||'',item.highlight||'');
    var optionsEl=$('practiceOptions');
    optionsEl.innerHTML='';
    (item.options||[]).forEach(function(opt,i){
        var btn=document.createElement('button');
        btn.type='button';
        btn.className='practice-option';
        btn.dataset.value=opt;
        btn.innerHTML='<span class="practice-option-num">'+(i+1)+'</span><span>'+escapeHtml(opt)+'</span>';
        btn.onclick=function(){selectPracticeOption(opt,btn);};
        btn.style.setProperty('--i',i);
        btn.classList.add('is-arriving');
        btn.addEventListener('animationend',function(){btn.classList.remove('is-arriving');},{once:true});
        optionsEl.appendChild(btn);
    });
    $('practiceFeedback').textContent='';
    $('practiceFeedback').className='practice-feedback';
    $('practiceNextBtn').style.display='none';
    $('practiceNextBtn').textContent=practiceIndex===practiceItems.length-1?'See results':'Next';
}

function renderPracticeTranslation(text,highlight){
    text=String(text||'').trim();
    if(!text)return '';
    highlight=String(highlight||'').trim();
    if(!highlight)return escapeHtml(text);
    var lowerText=text.toLocaleLowerCase();
    var lowerHighlight=highlight.toLocaleLowerCase();
    var idx=lowerText.indexOf(lowerHighlight);
    if(idx<0)return escapeHtml(text);
    return escapeHtml(text.slice(0,idx))
        +'<span class="practice-translation-target">'
        +escapeHtml(text.slice(idx,idx+highlight.length))
        +'</span>'
        +escapeHtml(text.slice(idx+highlight.length));
}

function selectPracticeOption(picked,btnEl){
    var item=practiceItems[practiceIndex];
    if(!item)return;
    var allOptions=document.querySelectorAll('#practiceOptions .practice-option');
    allOptions.forEach(function(o){o.disabled=true;o.classList.remove('is-arriving');});
    var correct=String(picked).toLowerCase()===String(item.answer).toLowerCase();
    var blankEl=$('practiceBlank');
    if(correct){
        practiceCorrect++;
        btnEl.classList.add('is-correct');
        if(blankEl){
            blankEl.classList.add('filled');
            blankEl.textContent=item.answer;
        }
        $('practiceFeedback').className='practice-feedback is-correct';
        $('practiceFeedback').innerHTML='<strong>Correct.</strong>'+(item.meaning?' - '+escapeHtml(item.meaning):'');
    }else{
        practiceWrong++;
        btnEl.classList.add('is-wrong');
        allOptions.forEach(function(o){
            if(String(o.dataset.value||'').toLowerCase()===String(item.answer||'').toLowerCase())o.classList.add('is-correct');
        });
        if(blankEl){
            blankEl.classList.add('wrong');
            blankEl.textContent=picked;
        }
        $('practiceFeedback').className='practice-feedback is-wrong';
        $('practiceFeedback').innerHTML='Answer: <strong>'+escapeHtml(item.answer)+'</strong>'+(item.meaning?' ('+escapeHtml(item.meaning)+')':'');
    }
    var changed=correct?$('practiceCorrectCount'):$('practiceWrongCount');
    $('practiceCorrectCount').textContent=String(practiceCorrect);
    $('practiceWrongCount').textContent=String(practiceWrong);
    if(window.ivyReplay)ivyReplay(changed,'ticked');
    $('practiceNextBtn').style.display='inline-flex';
    fetch('/api/practice/answer',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({word:item.answer,target_lang:$('practiceLang').value,correct:correct})
    }).catch(function(){});
}

function advancePracticeQuiz(){
    practiceIndex++;
    if(practiceIndex>=practiceItems.length)finishPracticeQuiz();
    else renderPracticeItem();
}

function finishPracticeQuiz(){
    var total=practiceCorrect+practiceWrong;
    var pct=total?Math.round((practiceCorrect/total)*100):0;
    $('practiceResultsScore').textContent=practiceCorrect+'/'+total;
    if(window.ivyCountTo){$('practiceResultsPct').dataset.value='0';ivyCountTo($('practiceResultsPct'),pct,'% correct');}
    else $('practiceResultsPct').textContent=pct+'% correct';
    var msg='Tough round. The words you missed will come back sooner in review.';
    if(pct>=90)msg='Excellent recall. These words are sticking.';
    else if(pct>=70)msg='Solid work. A few words are ready for another pass.';
    else if(pct>=50)msg='Halfway there. Try the same context again to lock it in.';
    $('practiceResultsMsg').textContent=msg;
    $('practiceProgressFill').style.width='100%';
    showPracticeView('results');
}

function quitPracticeQuiz(){
    practiceItems=[];
    practiceIndex=0;
    practiceCorrect=0;
    practiceWrong=0;
    showPracticeView('setup');
}

function isKeyboardEditableTarget(target){
    var tagName=target&&target.tagName?target.tagName.toUpperCase():'';
    return !!(target&&(target.isContentEditable||tagName==='INPUT'||tagName==='TEXTAREA'||tagName==='SELECT'));
}

function handlePracticeKeyboard(e){
    if(currentMode!=='practice'||practiceState!=='quiz')return false;
    if(isKeyboardEditableTarget(e.target))return false;

    var nextBtn=$('practiceNextBtn');
    var answered=!!(nextBtn&&nextBtn.style.display!=='none');
    var numberKey='';
    if(/^[1-4]$/.test(e.key))numberKey=e.key;
    else if(/^Numpad[1-4]$/.test(e.code))numberKey=e.code.replace('Numpad','');

    if(numberKey&&!answered){
        var option=document.querySelectorAll('#practiceOptions .practice-option')[parseInt(numberKey,10)-1];
        if(option&&!option.disabled){
            e.preventDefault();
            option.click();
            return true;
        }
    }

    if((e.key==='Enter'||e.key===' '||e.code==='Space')&&answered){
        e.preventDefault();
        nextBtn.click();
        return true;
    }

    return false;
}

// Flashcards
function setFlashcardLang(el,lang){
    currentFlashcardLang=lang;
    currentFlashcardSetId=null;
    document.querySelectorAll('.flashcard-filter').forEach(function(btn){
        btn.classList.toggle('active',btn.dataset.lang===lang);
    });
    loadFlashcards(lang);
}

async function loadFlashcards(lang){
    currentFlashcardLang=lang||currentFlashcardLang||$('tgtLang').value||'tr';
    if(!currentUser){renderFlashcardFilters([]);renderFlashcardSetFilter();$('fcProgress').textContent='';$('fcContent').innerHTML='<div class="flashcard-done"><h2>Log in required</h2><p>Create an account to use flashcards</p></div>';$('fcActions').style.display='none';requestAnimationFrame(syncModeStageHeight);return;}
    var availableLangs=await getFlashcardLanguages(currentFlashcardLang);
    if(availableLangs.length===0){renderFlashcardFilters([]);renderFlashcardSetFilter();$('fcProgress').textContent='';$('fcContent').innerHTML='<div class="flashcard-done"><h2>No flashcards yet</h2><p>Save a few translated words to vocabulary first, then come back here to study them.</p></div>';$('fcActions').style.display='none';requestAnimationFrame(syncModeStageHeight);return;}
    if(availableLangs.indexOf(currentFlashcardLang)===-1)currentFlashcardLang=availableLangs[0];
    renderFlashcardFilters(availableLangs);
    await refreshFlashcardSets();
    renderFlashcardSetFilter();
    var url='/api/flashcards/due?lang='+encodeURIComponent(currentFlashcardLang);
    if(currentFlashcardSetId)url+='&set_id='+encodeURIComponent(currentFlashcardSetId);
    try{var r=await fetch(url);var d=await r.json();flashcards=d.cards||[];fcIndex=0;
    if(flashcards.length===0){
        $('fcProgress').textContent=flashcardDeckLabel();
        var emptyMsg=currentFlashcardSetId
            ? 'No cards due in this set. The SRS will resurface words when their next review comes up.'
            : 'No cards due for '+(langNames[currentFlashcardLang]||currentFlashcardLang)+'. Save more words or review another saved language.';
        $('fcContent').innerHTML='<div class="flashcard-done"><h2>All done!</h2><p>'+emptyMsg+'</p></div>';
        $('fcActions').style.display='none';requestAnimationFrame(syncModeStageHeight);
    }
    else showFlashcard();}catch(e){console.error(e);}
}

function flashcardDeckLabel(){
    var langPart=(langNames[currentFlashcardLang]||currentFlashcardLang)+' deck';
    if(!currentFlashcardSetId)return langPart;
    var set=availableFlashcardSets.find(function(s){return s.id===currentFlashcardSetId;});
    return langPart+' - '+(set?set.name:'set #'+currentFlashcardSetId);
}

async function refreshFlashcardSets(){
    if(!currentUser){availableFlashcardSets=[];return;}
    try{
        var r=await fetch('/api/sets/list');
        var d=await r.json();
        availableFlashcardSets=(d.sets||[]).filter(function(s){
            return !s.target_lang||s.target_lang===currentFlashcardLang;
        });
    }catch(e){availableFlashcardSets=[];}
    if(currentFlashcardSetId&&!availableFlashcardSets.some(function(s){return s.id===currentFlashcardSetId;})){
        currentFlashcardSetId=null;
    }
}

function renderFlashcardSetFilter(){
    var row=$('fcSetRow'),sel=$('fcSetSelect'),clear=$('fcSetClear');
    if(!row||!sel)return;
    if(!currentUser||availableFlashcardSets.length===0){row.style.display='none';return;}
    row.style.display='flex';
    var options=['<option value="">All due cards</option>'];
    availableFlashcardSets.forEach(function(s){
        var selected=currentFlashcardSetId===s.id?' selected':'';
        var label=(s.name||'Untitled')+' ('+(s.word_count||0)+')';
        options.push('<option value="'+s.id+'"'+selected+'>'+escapeHtml(label)+'</option>');
    });
    sel.innerHTML=options.join('');
    if(currentFlashcardSetId){row.classList.add('has-filter');clear.style.display='inline-block';}
    else{row.classList.remove('has-filter');clear.style.display='none';}
}

function onFlashcardSetChange(){
    var sel=$('fcSetSelect');if(!sel)return;
    currentFlashcardSetId=sel.value?parseInt(sel.value,10):null;
    loadFlashcards(currentFlashcardLang);
}

function clearFlashcardSetFilter(){
    currentFlashcardSetId=null;
    loadFlashcards(currentFlashcardLang);
}

function showFlashcard(){
    if(fcIndex>=flashcards.length){$('fcContent').innerHTML='<div class="flashcard-done"><h2>Session complete!</h2><p>Reviewed '+flashcards.length+' cards</p></div>';$('fcActions').style.display='none';requestAnimationFrame(syncModeStageHeight);return;}
    var c=flashcards[fcIndex];var tags='';if(c.pos)tags+='<span class="vocab-tag tag-pos">'+escapeHtml(c.pos)+'</span>';if(c.grammatical_case)tags+='<span class="vocab-tag tag-case">'+escapeHtml(c.grammatical_case)+'</span>';if(c.difficulty)tags+='<span class="vocab-tag tooltip-cefr cefr-'+escapeHtml(c.difficulty)+'">'+escapeHtml(c.difficulty)+'</span>';
    $('fcProgress').textContent=flashcardDeckLabel()+' - card '+(fcIndex+1)+' of '+flashcards.length;
    $('fcContent').innerHTML='<div class="flashcard" onclick="this.classList.toggle(\'flipped\')"><div class="flashcard-lang">'+(langNames[c.target_lang]||c.target_lang)+'</div><div class="flashcard-word">'+escapeHtml(c.word)+'</div>'+(c.base_form&&c.base_form!==c.word?'<div class="flashcard-base">'+escapeHtml(c.base_form)+'</div>':'')+'<div class="flashcard-tags">'+tags+'</div><div class="flashcard-reveal">tap to reveal</div><div class="flashcard-answer"><div class="flashcard-answer-inner"><div class="flashcard-meaning">'+escapeHtml(c.meaning||'—')+'</div>'+(c.sentence?'<div class="flashcard-sentence">'+escapeHtml(c.sentence)+'</div>':'')+'</div></div></div>';
    if(window.ivyReplay)ivyReplay($('fcContent').querySelector('.flashcard'),'is-entering');
    $('fcActions').style.display='flex';
    requestAnimationFrame(syncModeStageHeight);
}
async function reviewCard(q){
    var c=flashcards[fcIndex];
    if(!c||reviewCard.busy)return;
    reviewCard.busy=true;
    var card=$('fcContent').querySelector('.flashcard');
    var leaving=new Promise(function(resolve){
        if(!card||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return resolve();
        card.classList.add('is-leaving');
        setTimeout(resolve,170);
    });
    try{await fetch('/api/flashcards/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vocab_id:c.id,quality:q})});}catch(e){}
    await leaving;
    reviewCard.busy=false;
    fcIndex++;showFlashcard();
}

function updateSaveStoryButton(state){
    var btn=$('saveStoryBtn');
    if(!btn)return;
    if(state==='saving'){
        btn.disabled=true;
        btn.textContent='Saving…';
        return;
    }
    if(state==='analyzing'){
        btn.disabled=true;
        btn.textContent='Analyzing words…';
        return;
    }
    if(currentStory&&currentStory.saved){
        btn.disabled=true;
        btn.innerHTML='Saved &#10003;';
        return;
    }
    if(currentStory&&currentStory._wordAnalysisPromise){
        btn.disabled=true;
        btn.textContent='Analyzing words…';
        return;
    }
    if(!currentUser){
        btn.disabled=false;
        btn.textContent='Save story';
        return;
    }
    btn.disabled=false;
    btn.textContent='Save story';
}

async function saveFocusWord(event,index){
    event.stopPropagation();
    var btn=event.target;
    if(btn.classList.contains('saved'))return;
    if(!currentUser){openAuth();return;}
    var focusItem=(currentStory&&currentStory.focus_vocabulary)?currentStory.focus_vocabulary[index]:null;
    if(!focusItem)return;
    var data={
        word:focusItem.word||'',
        meaning:focusItem.meaning||'',
        pos:'',
        "case":'',
        gender:'',
        base_form:focusItem.word||'',
        difficulty:currentStory?currentStory.cefr_level:'',
        sentence:currentStory?sentenceForWord(currentStory.story_text,focusItem.word):'',
        translation:currentStory?currentStory.summary:'',
        source_lang:currentStory?currentStory.target_lang:'',
        target_lang:currentStory?currentStory.target_lang:'',
        style:currentStory?currentStory.style:'neutral'
    };
    try{
        await fetch('/api/vocab/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        savedVocabKeys.add(vocabKey(focusItem.word,currentStory?currentStory.target_lang:''));
        btn.innerHTML='&#10003;';
        btn.classList.add('saved');
        refreshVocabCounts();
    }catch(e){
        btn.textContent='!';
    }
}

async function saveCurrentStory(){
    if(!currentStory){return;}
    if(!currentUser){openAuth();return;}
    var storyToSave=currentStory;
    if(storyToSave.saved){
        $('storyStatus').textContent='This story is already saved.';
        updateSaveStoryButton();
        return;
    }
    try{
        if(!(storyToSave.word_data||[]).length){
            $('storyStatus').textContent='Finishing word analysis before saving…';
            updateSaveStoryButton('analyzing');
            await ensureStoryWordAnalysisReady(storyToSave);
        }
        if(currentStory!==storyToSave)return;
        if(!(storyToSave.word_data||[]).length){
            throw new Error('Ivy could not finish word analysis yet. Try saving again in a moment.');
        }
        $('storyStatus').textContent='Saving story…';
        updateSaveStoryButton('saving');
        var payload={
            title:storyToSave.title,
            story_text:storyToSave.story_text,
            summary:storyToSave.summary,
            target_lang:storyToSave.target_lang,
            support_lang:storyToSave.support_lang,
            cefr_level:storyToSave.cefr_level,
            theme:storyToSave.theme,
            length_label:storyToSave.length_label,
            comprehension_json:JSON.stringify(storyToSave.comprehension_questions||[]),
            focus_vocab_json:JSON.stringify(storyToSave.focus_vocabulary||[]),
            word_data_json:JSON.stringify(storyToSave.word_data||[])
        };
        var r=await fetch('/api/stories/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        var d=await r.json();
        if(d.error)throw new Error(d.error);
        storyToSave.saved=true;
        storyToSave.id=d.story_id;
        try{
            await persistStoryAudioIfNeeded(storyToSave);
        }catch(e){
            console.warn('Audio upload failed:',e);
        }
        $('storyStatus').textContent=d.already_saved?'Already in your story shelf.':'Saved to your story shelf.';
        updateSaveStoryButton();
        loadSavedStories();
    }catch(e){
        $('storyStatus').textContent=e.message||'Could not save story.';
        if(currentStory===storyToSave)storyToSave.saved=false;
        updateSaveStoryButton();
    }
}

async function loadSavedStories(){
    if(!currentUser){$('savedStoriesList').innerHTML='<div class="story-empty">Log in to save stories for later review.</div>';return;}
    try{
        var r=await fetch('/api/stories/list');
        var d=await r.json();
        if(d.error){$('savedStoriesList').innerHTML='<div class="story-empty">'+escapeHtml(d.error)+'</div>';return;}
        if(!d.stories||d.stories.length===0){$('savedStoriesList').innerHTML='<div class="story-empty">No saved stories yet. Generate one you want to revisit.</div>';return;}
        $('savedStoriesList').innerHTML=d.stories.map(function(story){
            return '<div class="saved-story-card" role="button" tabindex="0" onclick="openSavedStory('+story.id+')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();openSavedStory('+story.id+');}"><div class="saved-story-top"><div><div class="saved-story-title">'+escapeHtml(story.title)+'</div><div class="saved-story-meta">'+escapeHtml((langNames[story.target_lang]||story.target_lang)+' • '+story.cefr_level+' • '+(story.theme||'story'))+'</div></div><button class="saved-story-delete" onclick="deleteSavedStory(event,'+story.id+')">&times;</button></div></div>';
        }).join('');
    }catch(e){
        $('savedStoriesList').innerHTML='<div class="story-empty">Could not load saved stories.</div>';
    }
}

function isDisplayedStory(story){
    return !!(story&&currentStory&&(currentStory===story||(story.id&&currentStory.id===story.id)));
}

function applyStoryWordAnalysis(story,wordData,readyMessage){
    if(!story||!wordData||!wordData.length)return [];
    story.word_data=enrichWordDataWithFocus(wordData,story.focus_vocabulary||[]);
    if(isDisplayedStory(story)){
        lastWordData=story.word_data;
        $('storyText').innerHTML=renderWords(story.word_data,{storyAudio:true,sourceText:story.story_text||''});
        $('storyText').classList.remove('empty');
        setKaraokeAvailable(true);
        clearKaraokeHighlights();
        if(readyMessage)setStoryStatus(readyMessage,'ready');
        maybeAutoPrepareKaraoke();
    }
    return story.word_data;
}

function startStoryWordAnalysis(story,readyMessage){
    if(!story||!(story.story_text||'').trim())return Promise.resolve([]);
    if(story._wordAnalysisPromise)return story._wordAnalysisPromise;
    var analysisPromise=analyzeStoryWords(story.story_text,story.target_lang).then(function(wordData){
        return applyStoryWordAnalysis(story,wordData,readyMessage);
    }).catch(function(){
        return [];
    });
    story._wordAnalysisPromise=analysisPromise;
    updateSaveStoryButton();
    analysisPromise.finally(function(){
        if(story._wordAnalysisPromise===analysisPromise){
            story._wordAnalysisPromise=null;
        }
        if(isDisplayedStory(story)){
            updateSaveStoryButton();
        }
    });
    return analysisPromise;
}

async function ensureStoryWordAnalysisReady(story){
    if(!story)return false;
    if((story.word_data||[]).length>0)return true;
    if(story._wordAnalysisPromise){
        await story._wordAnalysisPromise;
    }
    if((story.word_data||[]).length>0)return true;
    await startStoryWordAnalysis(story,'Story ready. Hover words to inspect and save vocabulary.');
    return (story.word_data||[]).length>0;
}

function savedStoryAudioUrl(storyId){
    return '/api/stories/'+encodeURIComponent(storyId)+'/audio';
}

function savedStoryNarrationUrl(storyId){
    return '/api/stories/'+encodeURIComponent(storyId)+'/narration';
}

function blobToBase64(blob){
    return new Promise(function(resolve,reject){
        var reader=new FileReader();
        reader.onload=function(){
            var result=String(reader.result||'');
            resolve(result.indexOf(',')>=0?result.split(',',2)[1]:result);
        };
        reader.onerror=function(){reject(reader.error||new Error('Could not read audio blob.'));};
        reader.readAsDataURL(blob);
    });
}

function sameAudioSource(player,url){
    if(!player||!url)return false;
    return player.src===new URL(url,window.location.href).href;
}

function applyCachedStoryAudio(story){
    if(!story||!story.id||!story.has_audio)return;
    story.audio_url=savedStoryAudioUrl(story.id);
    if(currentStory&&currentStory.id===story.id){
        currentStory.audio_url=story.audio_url;
    }
    var player=$('storyAudioPlayer');
    if(player){
        player.src=story.audio_url;
        player.load();
        syncStoryAudioUI();
    }
}

async function persistStoryAudioIfNeeded(story){
    if(!story||!story.id||!story.audio_url||story.audio_url.indexOf('blob:')!==0)return;
    var blobUrl=story.audio_url;
    var blobResp=await fetch(blobUrl);
    var blob=await blobResp.blob();
    var player=$('storyAudioPlayer');
    var playerWasUsingBlob=player&&sameAudioSource(player,blobUrl);
    var playerIsPlaying=playerWasUsingBlob&&!player.paused&&!player.ended;
    var hasSyncedNarration=Array.isArray(story.timepoints)&&story.timepoints.length>0;
    if(hasSyncedNarration){
        var audioB64=currentStoryNarrationB64||await blobToBase64(blob);
        await fetch(savedStoryNarrationUrl(story.id),{
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({audio_b64:audioB64,timepoints:story.timepoints})
        });
        story.has_narration=true;
    }else{
        await fetch(savedStoryAudioUrl(story.id),{
            method:'PUT',
            headers:{'Content-Type':'audio/mpeg'},
            body:blob
        });
        story.has_narration=false;
    }
    story.has_audio=true;
    if(!playerIsPlaying){
        URL.revokeObjectURL(blobUrl);
        if(currentStoryAudioUrl===blobUrl)currentStoryAudioUrl='';
        story.audio_url=savedStoryAudioUrl(story.id);
        if(player&&playerWasUsingBlob){
            player.src=story.audio_url;
            player.load();
            syncStoryAudioUI();
        }
    }
}

async function deleteSavedStory(event,storyId){
    event.stopPropagation();
    try{
        await fetch('/api/stories/'+storyId,{method:'DELETE'});
        if(currentStory&&storyId===currentStory.id){$('storyStatus').textContent='Saved story deleted.';}
        loadSavedStories();
    }catch(e){
        $('storyStatus').textContent='Could not delete story.';
    }
}

function getModeView(mode){
    if(mode==='flashcards')return $('flashcardsView');
    if(mode==='stories')return $('storiesView');
    if(mode==='practice')return $('practiceView');
    return $('translateView');
}

function syncModeStageHeight(){
    var stage=$('modeStage');
    if(!stage)return;
    if(currentMode==='stories')updateStoryShellHeight();
    stage.style.minHeight='0px';
    stage.style.height='auto';
}

function scheduleModeStageHeightSync(){
    syncModeStageHeight();
}

function clearTranslatorOutputState(){
    translateRequestId++;
    compareRequestId++;
    abortTranslateRequest();
    abortCompareRequest();
    setOutputEmpty('Translation appears here…',defaultOutputHint);
    $('outCharCount').innerHTML='&nbsp;';
    $('analysisRow').style.display='none';
    $('posLegend').style.display='none';
    $('speakBtn').style.display='none';
    $('ivyWhyBtn').classList.remove('visible');
    $('copyTranslationBtn').classList.remove('visible','copied');
    $('copyTranslationBtn').textContent='Copy';
    $('vulgarBadge').classList.remove('visible');
    $('typingIndicator').classList.remove('visible');
    $('compareResults').style.display='none';
    showAiNotice('');
    $('cmpFormal').textContent='';
    $('cmpNeutral').textContent='';
    $('cmpCasual').textContent='';
    lastTranslation='';
    lastWordData=[];
    lastTranslationSource='';
    activeWordSourceText='';
    activeWordTranslationText='';
    closeIvyPanel();
}

function abortTranslateRequest(){
    if(translateAbortController){
        try{translateAbortController.abort();}catch(e){}
        translateAbortController=null;
    }
    isTranslating=false;
}

function abortCompareRequest(){
    if(compareAbortController){
        try{compareAbortController.abort();}catch(e){}
        compareAbortController=null;
    }
}

function isCurrentTranslateRequest(requestId,snapshot){
    return requestId===translateRequestId
        && currentMode==='translate'
        && inputArea.value.trim()===snapshot.text
        && $('srcLang').value===snapshot.source_lang
        && $('tgtLang').value===snapshot.target_lang
        && currentStyle===snapshot.style;
}

function isCurrentCompareRequest(requestId,snapshot){
    return requestId===compareRequestId
        && currentMode==='compare'
        && inputArea.value.trim()===snapshot.text
        && $('srcLang').value===snapshot.source_lang
        && $('tgtLang').value===snapshot.target_lang;
}

// Mode
function setMode(mode){
    var previousMode=currentMode;
    currentMode=mode;
    document.querySelectorAll('.mode-tab').forEach(function(t){
        var on=t.dataset.mode===mode;
        t.classList.toggle('active',on);
        if(on){
            t.setAttribute('aria-current','page');
            if(t.scrollIntoView)t.scrollIntoView({block:'nearest',inline:'nearest'});
        }else t.removeAttribute('aria-current');
    });
    var hash=mode==='translate'?'':'#'+mode;
    if(window.location.hash!==hash)history.replaceState(null,'',window.location.pathname+window.location.search+hash);
    $('langBar').style.display=(mode==='flashcards'||mode==='stories'||mode==='practice')?'none':'flex';
    // Compare mode: expand input panel, hide output panel
    var grid=$('translatorGrid');
    if(mode==='compare'){grid.classList.add('compare-mode');$('compareResults').style.display='none';$('analysisRow').style.display='none';$('posLegend').style.display='none';}
    else{grid.classList.remove('compare-mode');$('compareResults').style.display='none';}
    if(mode!=='translate'){
        $('speakBtn').style.display='none';
        $('ivyWhyBtn').classList.remove('visible');
        closeIvyPanel();
    }else if(lastTranslationSource!=='translate'){
        clearTranslatorOutputState();
    }else if((lastTranslation||'').trim()){
        $('speakBtn').style.display='inline-flex';
        $('ivyWhyBtn').classList.add('visible');
        $('copyTranslationBtn').classList.add('visible');
    }
    $('translateView').style.display=(mode==='translate'||mode==='compare')?'block':'none';
    $('flashcardsView').classList.toggle('visible',mode==='flashcards');
    $('storiesView').classList.toggle('visible',mode==='stories');
    $('practiceView').classList.toggle('visible',mode==='practice');
    if(mode==='compare'&&previousMode!=='compare'&&$('inputArea').value.trim().length>2){
        scheduleCompare();
    }
    if(mode==='translate'&&previousMode==='compare'&&$('inputArea').value.trim().length>2&&!lastTranslation){
        scheduleTranslation();
    }
    if(mode==='flashcards'){
        currentFlashcardLang=currentFlashcardSetId?(currentFlashcardLang||$('tgtLang').value||'tr'):($('tgtLang').value||currentFlashcardLang||'tr');
        loadFlashcards(currentFlashcardLang);
    }
    if(mode==='stories'){
        if(!localStorage.getItem('ivy-story-target-lang'))$('storyTargetLang').value=$('tgtLang').value||'tr';
        saveStoryPreferences();
        loadSavedStories();
        updateStoryShellHeight();
    }
    if(mode==='practice')initPracticeMode();
}
function setStyle(el){document.querySelectorAll('.style-chip').forEach(function(c){c.classList.remove('active');c.setAttribute('aria-pressed','false');});el.classList.add('active');el.setAttribute('aria-pressed','true');currentStyle=el.dataset.style;if(currentMode==='translate'&&$('inputArea').value.trim().length>2)scheduleTranslation();}
function swapLangs(){var s=$('srcLang'),t=$('tgtLang');var tmp=s.value;s.value=t.value;t.value=tmp;checkRestyleMode();rescheduleForCurrentMode();}
function clearInput(){ $('inputArea').value='';$('charCount').textContent='0';$('detectedBadge').classList.remove('visible');clearTranslatorOutputState();}
function speakTranslation(){if(!lastTranslation||lastTranslationSource!=='translate')return;var u=new SpeechSynthesisUtterance(lastTranslation);u.lang={tr:'tr-TR',ru:'ru-RU',de:'de-DE',en:'en-US'}[$('tgtLang').value]||'en-US';u.rate=0.9;speechSynthesis.cancel();speechSynthesis.speak(u);}

async function copyTranslation(){
    if(!lastTranslation||lastTranslationSource!=='translate')return;
    var btn=$('copyTranslationBtn');
    try{
        if(navigator.clipboard&&navigator.clipboard.writeText){
            await navigator.clipboard.writeText(lastTranslation);
        }else{
            var textarea=document.createElement('textarea');
            textarea.value=lastTranslation;
            textarea.setAttribute('readonly','');
            textarea.style.position='fixed';
            textarea.style.left='-9999px';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }
        if(btn){
            btn.textContent='Copied';
            btn.classList.add('copied');
            setTimeout(function(){
                btn.textContent='Copy';
                btn.classList.remove('copied');
            },1200);
        }
    }catch(e){
        if(btn){
            btn.textContent='Error';
            setTimeout(function(){btn.textContent='Copy';},1200);
        }
    }
}

var ivyExplainToken=0;
var ivyExplainCache={};

function renderIvyMarkdown(text){
    var lines=String(text||'').split(/\r?\n/);
    var out=[],inList=false;
    function inline(s){
        s=escapeHtml(s);
        s=s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
        s=s.replace(/(^|[^\*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
        s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
        return s;
    }
    for(var i=0;i<lines.length;i++){
        var line=lines[i].replace(/\s+$/,'');
        var bullet=line.match(/^\s*[-*\u2022]\s+(.*)$/);
        if(bullet){
            if(!inList){out.push('<ul>');inList=true;}
            out.push('<li>'+inline(bullet[1])+'</li>');
        }else if(line.trim()===''){
            if(inList){out.push('</ul>');inList=false;}
        }else{
            if(inList){out.push('</ul>');inList=false;}
            out.push('<p>'+inline(line)+'</p>');
        }
    }
    if(inList)out.push('</ul>');
    return out.join('');
}

function closeIvyPanel(){
    ivyExplainToken++;
    var panel=$('ivyExplanationPanel');
    if(!panel)return;
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden','true');
    var btn=$('ivyWhyBtn');
    if(btn)btn.classList.remove('is-thinking');
}

async function askIvyWhy(){
    if(currentMode!=='translate'||lastTranslationSource!=='translate'){
        closeIvyPanel();
        return;
    }
    var sentence=(lastTranslation||'').trim();
    if(!sentence)return;
    var targetLang=$('tgtLang').value;
    var supportLang=$('srcLang').value;
    if(targetLang===supportLang)supportLang='en';
    var cacheKey=targetLang+'|'+supportLang+'|'+sentence;
    var panel=$('ivyExplanationPanel');
    var content=$('ivyPanelContent');
    var sentenceEl=$('ivyPanelSentence');
    var btn=$('ivyWhyBtn');
    if(!panel||!content||!sentenceEl||!btn)return;

    sentenceEl.textContent=sentence;
    panel.classList.add('open');
    panel.setAttribute('aria-hidden','false');

    if(ivyExplainCache[cacheKey]){
        content.innerHTML=ivyExplainCache[cacheKey];
        return;
    }

    btn.classList.add('is-thinking');
    var logoSrc=$('ivyPanelLogo')?$('ivyPanelLogo').src:'/static/logo-mark-dark-128.png';
    content.innerHTML='<div class="ivy-panel-loading"><img src="'+escapeHtml(logoSrc)+'" alt=""><div>Ivy is breaking it down…</div></div>';
    var myToken=++ivyExplainToken;

    try{
        var r=await fetch('/api/explain_sentence',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sentence:sentence,target_lang:targetLang,support_lang:supportLang})});
        if(myToken!==ivyExplainToken)return;
        var d=await r.json();
        if(myToken!==ivyExplainToken)return;
        if(!r.ok||d.error)throw new Error(d.error||'Could not explain right now.');
        var html=renderIvyMarkdown(d.explanation||'');
        ivyExplainCache[cacheKey]=html;
        content.innerHTML=html;
    }catch(e){
        if(myToken!==ivyExplainToken)return;
        content.innerHTML='<div class="ivy-panel-error">Ivy could not explain right now. '+escapeHtml(e.message||'')+'</div>';
    }finally{
        if(myToken===ivyExplainToken)btn.classList.remove('is-thinking');
    }
}

var outputArea=$('outputArea');
var inputArea=$('inputArea');

// Render words
    var PUNCT_HUG_PREV = /^[,.!?;:)\]}"'…\u201D\u2019\u3002\uFF01\uFF1F\uFF0C\uFF1B\uFF1A]/;
    function isPureWordPunct(s){
        var t = String(s||'').trim();
        if(!t) return true;
        return !/[\p{L}\p{N}]/u.test(t);
    }
    function stripTrailingPunct(s){
        return String(s||'').replace(/^[\p{P}\s]+|[\p{P}\s]+$/gu, '');
    }

    function displayTokenPattern(){
        return /[\p{L}\p{M}\p{N}]+(?:[''\u2019-][\p{L}\p{M}\p{N}]+)*/gu;
    }

    function normalizeWordToken(value){
        return stripTrailingPunct(value).toLocaleLowerCase();
    }

    function nextWordDataIndex(wordData, start, displayToken){
        var firstUsable=-1;
        var target=normalizeWordToken(displayToken);
        for(var i=start;i<wordData.length;i++){
            var item=wordData[i]||{};
            if(isPureWordPunct(item.word))continue;
            if(firstUsable<0)firstUsable=i;
            var itemWord=normalizeWordToken(item.word);
            var itemBase=normalizeWordToken(item.base_form||'');
            if(target&&(itemWord===target||itemBase===target))return i;
            if(firstUsable>=0&&i-firstUsable>=4)break;
        }
        return firstUsable;
    }

    function renderWordSpan(w, index, displayWord, allowStoryAudio){
        var shownWord=displayWord||w.word||'';
        var pos = normalizeDisplayPos(w.pos,w.word), meaning = w.meaning || focusMeaningForWord(w.word) || '', baseForm = w.base_form || w.word, caseInfo = w['case'] || '', gender = w.gender || '', diff = w.difficulty || '', vulgar = w.vulgar || false;
        var safePos=escapeHtml(pos);
        var tags = '<span class="tooltip-tag tag-pos">' + safePos + '</span>';
        if (caseInfo) tags += '<span class="tooltip-tag tag-case">' + escapeHtml(caseInfo) + '</span>';
        if (gender) { var gm = { m: 'masc', f: 'fem', n: 'neut' }; tags += '<span class="tooltip-tag tag-gender">' + escapeHtml(gm[gender] || gender) + '</span>'; }
        if (vulgar) tags += '<span class="tooltip-tag" style="background:rgba(239,68,68,0.1);color:#ef4444;">vulgar</span>';
        var vulgarClass = vulgar ? ' word-vulgar' : '';
        var speakButton = allowStoryAudio ? '<button type="button" class="tooltip-speak" onmouseenter="prefetchStoryWordAudio(' + index + ')" onclick="playStoryWordAudio(event,' + index + ')" aria-label="Listen to word" title="Listen to word"><span class="tooltip-speak-icon">&#128266;</span></button>' : '';
        return '<span class="word-span' + vulgarClass + '" tabindex="0" data-pos="' + safePos + '" data-index="' + index + '" data-vulgar="' + vulgar + '">' + escapeHtml(shownWord) + '<span class="tooltip"><div class="tooltip-header"><div><div class="tooltip-word-row"><div class="tooltip-word">' + escapeHtml(w.word) + (vulgar ? ' <span style="color:#ef4444;font-size:11px;">&#9888;</span>' : '') + '</div>' + speakButton + '</div>' + (baseForm !== w.word ? '<div class="tooltip-base">' + escapeHtml(baseForm) + '</div>' : '') + '</div>' + (diff ? '<span class="tooltip-cefr cefr-' + escapeHtml(diff) + '">' + escapeHtml(diff) + '</span>' : '') + '</div>' + (meaning ? '<div class="tooltip-meaning">' + escapeHtml(meaning) + '</div>' : '') + '<div class="tooltip-tags">' + tags + '</div><button class="tooltip-save" onclick="saveWord(event,' + index + ')">+ Save to vocabulary</button></span></span>';
    }

    function renderStoryGapSegment(segment, previousWordIndex, allowStoryAudio){
        if(!segment)return '';
        if(!allowStoryAudio||previousWordIndex<0)return escapeHtml(segment);
        return String(segment).replace(/\s+|\S+/g,function(piece){
            if(/^\s+$/.test(piece))return escapeHtml(piece);
            return '<span class="story-punct" data-after-index="'+previousWordIndex+'">'+escapeHtml(piece)+'</span>';
        });
    }

    function renderWordsFromSource(wordData, sourceText, options){
        var opts=options||{};
        var allowStoryAudio=!!opts.storyAudio;
        var text=String(sourceText||'');
        var html='';
        var lastOffset=0;
        var dataCursor=0;
        var previousDataIndex=-1;
        var match;
        var tokenRe=displayTokenPattern();
        while((match=tokenRe.exec(text))!==null){
            html+=renderStoryGapSegment(text.slice(lastOffset,match.index),previousDataIndex,allowStoryAudio);
            var dataIndex=nextWordDataIndex(wordData,dataCursor,match[0]);
            if(dataIndex>=0){
                html+=renderWordSpan(wordData[dataIndex],dataIndex,match[0],allowStoryAudio);
                dataCursor=dataIndex+1;
                previousDataIndex=dataIndex;
            }else{
                html+=escapeHtml(match[0]);
                previousDataIndex=-1;
            }
            lastOffset=match.index+match[0].length;
        }
        html+=renderStoryGapSegment(text.slice(lastOffset),previousDataIndex,allowStoryAudio);
        return html;
    }

    function renderWords(wordData, options) {
        var opts=options||{};
        var allowStoryAudio=!!opts.storyAudio;
        if(opts.sourceText){
            return renderWordsFromSource(wordData,opts.sourceText,opts);
        }
        var html = '';
        wordData.forEach(function (w, i) {
            var span = renderWordSpan(w,i,w.word,allowStoryAudio);
            if (i === 0 || PUNCT_HUG_PREV.test(w.word || '')) html += span;
            else html += ' ' + span;
        });
        return html;
    }

function stopStoryWordAudio(){
    if(currentWordAudio){
        currentWordAudio.pause();
        currentWordAudio.currentTime=0;
    }
    document.querySelectorAll('.tooltip-speak.is-playing').forEach(function(btn){
        btn.classList.remove('is-playing');
    });
}

function storyWordAudioRequest(index){
    if(currentMode!=='stories'||!currentStory||!Array.isArray(lastWordData)||!lastWordData[index])return null;
    var word=String(lastWordData[index].word||'').trim();
    if(!word)return null;
    var language=currentStory.target_lang||$('storyTargetLang').value||'tr';
    return {
        word:word,
        language:language,
        cacheKey:language+'|'+word.toLocaleLowerCase()
    };
}

async function getStoryWordAudioUrl(request){
    if(!request)return '';
    var cachedUrl=storyWordAudioCache.get(request.cacheKey);
    if(cachedUrl)return cachedUrl;
    if(storyWordAudioPending.has(request.cacheKey)){
        return await storyWordAudioPending.get(request.cacheKey);
    }
    var pending=fetch('/api/stories/tts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:'google',text:request.word,language:request.language})}).then(async function(response){
        if(!response.ok){
            var errorText='Could not play word audio.';
            try{
                var payload=await response.json();
                errorText=payload.error||errorText;
            }catch(e){}
            throw new Error(errorText);
        }
        var blob=await response.blob();
        var audioUrl=URL.createObjectURL(blob);
        storyWordAudioCache.set(request.cacheKey,audioUrl);
        return audioUrl;
    }).finally(function(){
        storyWordAudioPending.delete(request.cacheKey);
    });
    storyWordAudioPending.set(request.cacheKey,pending);
    return await pending;
}

function prefetchStoryWordAudio(index){
    var request=storyWordAudioRequest(index);
    if(!request||storyWordAudioCache.has(request.cacheKey)||storyWordAudioPending.has(request.cacheKey))return;
    getStoryWordAudioUrl(request).catch(function(){});
}

async function playStoryWordAudio(event,index){
    event.preventDefault();
    event.stopPropagation();
    var request=storyWordAudioRequest(index);
    if(!request)return;
    var button=event.currentTarget;
    var myToken=++storyWordAudioToken;
    stopStoryWordAudio();
    button.classList.add('is-playing');
    if(!currentWordAudio){
        currentWordAudio=new Audio();
        currentWordAudio.preload='auto';
        ['ended','pause'].forEach(function(eventName){
            currentWordAudio.addEventListener(eventName,function(){
                document.querySelectorAll('.tooltip-speak.is-playing').forEach(function(btn){
                    btn.classList.remove('is-playing');
                });
            });
        });
    }
    try{
        var audioUrl=await getStoryWordAudioUrl(request);
        if(myToken!==storyWordAudioToken)return;
        currentWordAudio.src=audioUrl;
        currentWordAudio.muted=false;
        currentWordAudio.volume=1;
        currentWordAudio.playbackRate=1;
        await currentWordAudio.play();
        if(myToken!==storyWordAudioToken)stopStoryWordAudio();
    }catch(e){
        if(myToken===storyWordAudioToken){
            button.classList.remove('is-playing');
            setStoryStatus(e.message||'Could not play word audio.','error');
        }
    }
}

function normalizeDisplayPos(pos,word){
    var cleaned=String(pos||'').toLowerCase();
    return cleaned||'other';
}

function enrichWordDataWithFocus(wordData,focusVocabulary){
    var list=Array.isArray(wordData)?wordData:[];
    var vocab=Array.isArray(focusVocabulary)?focusVocabulary:[];
    if(!list.length||!vocab.length)return list;
    var meaningMap={};
    vocab.forEach(function(item){
        var key=String((item&&item.word)||'').trim().toLocaleLowerCase();
        if(key&&!meaningMap[key]&&item.meaning){
            meaningMap[key]=item.meaning;
        }
    });
    return list.map(function(item){
        var next=Object.assign({},item);
        var key=String((next.word)||'').trim().toLocaleLowerCase();
        if(key&&meaningMap[key]&&!next.meaning){
            next.meaning=meaningMap[key];
        }
        return next;
    });
}

function renderStoryContent(story){
    currentStory=story||{};
    karaokeFetchToken++;
    karaokeDataPromise=null;
    currentStory.saved=!!currentStory.saved;
    currentStory.audio_url=currentStory.audio_url||'';
    currentStory.timepoints=Array.isArray(currentStory.timepoints)?currentStory.timepoints:[];
    currentStory.has_narration=!!currentStory.has_narration;
    currentStory.word_data=enrichWordDataWithFocus(currentStory.word_data||[],currentStory.focus_vocabulary||[]);
    lastTranslation=currentStory.story_text||'';
    lastTranslationSource='story';
    lastWordData=currentStory.word_data||[];
    activeWordSourceText=currentStory.story_text||'';
    activeWordTranslationText=currentStory.summary||'';
    activeWordSourceLang=currentStory.target_lang||$('storyTargetLang').value;
    activeWordTargetLang=currentStory.target_lang||$('storyTargetLang').value;
    activeWordStyle=currentStory.style||$('storyStyle').value;

    $('storyMeta').innerHTML=
        '<span class="story-badge level">'+escapeHtml(currentStory.cefr_level||'A2')+'</span>'+
        '<span class="story-badge theme">'+escapeHtml(currentStory.theme||'daily life')+'</span>'+
        '<span class="story-badge length">'+escapeHtml(currentStory.length_label||'short')+'</span>'+
        '<span class="story-badge style">'+escapeHtml(currentStory.style||'neutral')+'</span>';
    $('storyTitle').textContent=currentStory.title||'Untitled story';
    if((currentStory.word_data||[]).length>0){
        $('storyText').innerHTML=renderWords(currentStory.word_data,{storyAudio:true,sourceText:currentStory.story_text||''});
        $('storyText').classList.remove('empty');
    }else{
        $('storyText').textContent=currentStory.story_text||'';
        $('storyText').classList.toggle('empty',!(currentStory.story_text||''));
    }
    $('storySummary').textContent=currentStory.summary||'No summary returned.';
    $('storyQuestions').innerHTML=(currentStory.comprehension_questions||[]).length?(currentStory.comprehension_questions||[]).map(function(item){
        return '<div class="story-question"><div class="story-question-q">'+escapeHtml(item.question||'')+'</div><div class="story-question-a">'+escapeHtml(item.answer||'')+'</div></div>';
    }).join(''):'<div class="story-empty">Three quick check questions will appear here.</div>';
    $('storyVocab').innerHTML=(currentStory.focus_vocabulary||[]).length?(currentStory.focus_vocabulary||[]).map(function(item,index){
        return '<div class="story-vocab-item"><div class="story-vocab-main"><div class="story-vocab-word">'+escapeHtml(item.word||'')+'</div><div class="story-vocab-meaning">'+escapeHtml(item.meaning||'')+'</div></div><button class="story-vocab-save" data-index="'+index+'" onclick="saveFocusWord(event,'+index+')">+</button></div>';
    }).join(''):'<div class="story-empty">Vocabulary targets will appear here after generation.</div>';
    updateSaveStoryButton();
    if(savedVocabLang===currentStory.target_lang){
        markFocusVocabularySaved();
    }else{
        refreshSavedVocabState(currentStory.target_lang).then(markFocusVocabularySaved);
    }
    setKaraokeAvailable(Array.isArray(currentStory.word_data)&&currentStory.word_data.length>0);
    clearKaraokeHighlights();
    maybeAutoPrepareKaraoke();
}

async function analyzeStoryWords(text,targetLang){
    try{
        var r=await fetch('/api/stories/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text,target_lang:targetLang})});
        var d=await r.json();
        return d.word_data||[];
    }catch(e){
        return [];
    }
}

// Auto translate
inputArea.addEventListener('input',function(){
    var len=inputArea.value.length;$('charCount').textContent=len;
    clearTimeout(detectTimer);if(len>15)detectTimer=setTimeout(function(){detectStyleFn(inputArea.value,'detectedBadge','detectedDot','detectedText');},500);else $('detectedBadge').classList.remove('visible');
    if(len>2){if(currentMode==='compare')scheduleCompare();else scheduleTranslation();}
    else{clearTranslatorOutputState();}
});

function scheduleTranslation(){
    clearTimeout(translateTimer);
    compareRequestId++;
    abortCompareRequest();
    abortTranslateRequest();
    var requestId=++translateRequestId;
    var hadTranslation=lastTranslationSource==='translate'&&!outputArea.classList.contains('empty');
    lastTranslationSource='';
    $('typingIndicator').classList.add('visible');
    $('speakBtn').style.display='none';
    $('ivyWhyBtn').classList.remove('visible');
    $('copyTranslationBtn').classList.remove('visible','copied');
    $('copyTranslationBtn').textContent='Copy';
    closeIvyPanel();
    hideActiveTooltip();
    // Keep the last translation on screen, dimmed, until the new one lands.
    if(hadTranslation)outputArea.classList.add('is-stale');
    else setOutputEmpty('Translation appears here…',loadingOutputHint);
    translateTimer=setTimeout(function(){doTranslate(requestId);},800);
}
function scheduleCompare(){
    clearTimeout(translateTimer);
    translateRequestId++;
    abortTranslateRequest();
    abortCompareRequest();
    var requestId=++compareRequestId;
    $('typingIndicator').classList.add('visible');
    setCompareLoading();
    $('compareResults').style.display='block';
    translateTimer=setTimeout(function(){doCompare(requestId);},1000);
}

async function doTranslate(requestId){
    var snapshot={text:inputArea.value.trim(),source_lang:$('srcLang').value,target_lang:$('tgtLang').value,style:currentStyle};
    if(!snapshot.text||!isCurrentTranslateRequest(requestId,snapshot))return;
    isTranslating=true;
    var controller=new AbortController();
    translateAbortController=controller;
    $('speakBtn').style.display='none';$('ivyWhyBtn').classList.remove('visible');
    try{var r=await fetch('/api/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(snapshot),signal:controller.signal});
    var d=await r.json();
    if(!isCurrentTranslateRequest(requestId,snapshot))return;
    if(!r.ok||d.error||typeof d.translation!=='string'){var err=new Error(d.error||'Ivy couldn’t translate that. Please try again.');err.friendly=true;throw err;}
    showAiNotice(d.notice);
    lastTranslation=d.translation;lastWordData=d.word_data||[];lastTranslationSource='translate';
    activeWordSourceText=d.translation||'';
    activeWordTranslationText=snapshot.text;
    activeWordSourceLang=snapshot.target_lang;
    activeWordTargetLang=snapshot.target_lang;
    activeWordStyle=snapshot.style;
    outputArea.style.color='';
    outputArea.classList.remove('is-stale','is-failed');
    if(lastWordData.length>0){outputArea.innerHTML=renderWords(lastWordData,{sourceText:d.translation||''});$('posLegend').style.display='flex';}else{outputArea.textContent=d.translation;$('posLegend').style.display='none';}
    // Words arrive in reading order (motion.css staggers them by --i).
    outputArea.querySelectorAll('.word-span').forEach(function(span,i){span.style.setProperty('--i',i);});
    if(window.ivyReplay)ivyReplay(outputArea,'is-arriving');
        outputArea.classList.remove('empty'); checkVulgar(d.translation, d.word_data); $('outCharCount').textContent=d.translation.length;$('speakBtn').style.display='inline-flex';$('ivyWhyBtn').classList.add('visible');$('copyTranslationBtn').classList.add('visible');
    var is=await detectStyleScores(snapshot.text);
    if(!isCurrentTranslateRequest(requestId,snapshot))return;
    renderBars('inputBars',is);renderBars('outputBars',d.style_scores);$('analysisRow').style.display='grid';
    }catch(e){
        if(e&&e.name==='AbortError')return;
        if(!isCurrentTranslateRequest(requestId,snapshot))return;
        lastTranslationSource='';outputArea.classList.remove('is-stale');outputArea.classList.add('is-failed');outputArea.textContent=(e&&e.friendly)?e.message:'Ivy couldn’t reach the server. Check that the app is running and try again.';outputArea.classList.remove('empty');$('vulgarBadge').classList.remove('visible');$('speakBtn').style.display='none';$('ivyWhyBtn').classList.remove('visible');$('copyTranslationBtn').classList.remove('visible','copied');closeIvyPanel();$('outCharCount').innerHTML='&nbsp;';
    }
    finally{
        if(translateAbortController===controller)translateAbortController=null;
        if(requestId===translateRequestId){$('typingIndicator').classList.remove('visible');isTranslating=false;}
    }
}

    function checkVulgar(text, wordData) {
        var found = wordData && wordData.some(function (w) { return w.vulgar; });
        $('vulgarBadge').classList.toggle('visible', !!found);
    }

async function doCompare(requestId){
    var snapshot={text:inputArea.value.trim(),source_lang:$('srcLang').value,target_lang:$('tgtLang').value};
    if(!snapshot.text||!isCurrentCompareRequest(requestId,snapshot)){
        if(requestId===compareRequestId)$('typingIndicator').classList.remove('visible');
        return;
    }
    var controller=new AbortController();
    compareAbortController=controller;
    try{var r=await fetch('/api/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(snapshot),signal:controller.signal});
    var d=await r.json();
    if(!isCurrentCompareRequest(requestId,snapshot))return;
    if(!r.ok||d.error||!d.results){var err=new Error(d.error||'Ivy couldn’t compare that. Please try again.');err.friendly=true;throw err;}
    showAiNotice(d.notice);
    $('cmpFormal').textContent=d.results.formal.translation;$('cmpNeutral').textContent=d.results.neutral.translation;$('cmpCasual').textContent=d.results.casual.translation;
    document.querySelectorAll('#compareResults .compare-text').forEach(function(el){el.classList.remove('is-waiting');});
    document.querySelectorAll('#compareResults .compare-card').forEach(function(card,i){card.style.setProperty('--i',i);if(window.ivyReplay)ivyReplay(card,'is-arriving');});
    renderBars('compareInputBars',d.input_style);renderRadar(d.results);$('compareResults').style.display='block';requestAnimationFrame(syncModeStageHeight);
    }catch(e){
        if(e&&e.name==='AbortError')return;
        if(!isCurrentCompareRequest(requestId,snapshot))return;
        document.querySelectorAll('#compareResults .compare-text').forEach(function(el){el.classList.remove('is-waiting');});
        $('cmpFormal').textContent=(e&&e.friendly)?e.message:'Compare failed';$('cmpNeutral').textContent='Try again in a moment';$('cmpCasual').textContent='';console.error(e);
    }
    finally{
        if(compareAbortController===controller)compareAbortController=null;
        if(requestId===compareRequestId)$('typingIndicator').classList.remove('visible');
    }
}

// Style detection
async function detectStyleFn(text,bId,dId,tId){try{var r=await fetch('/api/detect-style',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});var d=await r.json();var c={formal:'#22d3ee',casual:'#fb923c',neutral:'#64748b'};$(dId).style.background=c[d.dominant_style];$(tId).textContent=d.dominant_style;$(bId).classList.add('visible');}catch(e){}}
async function detectStyleScores(text){try{var r=await fetch('/api/detect-style',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:text})});return(await r.json()).scores;}catch(e){return{formal:0.33,casual:0.33,neutral:0.34};}}
function renderBars(id,scores){
    var rows=[{key:'formal',label:'Formal',color:'var(--formal)'},{key:'neutral',label:'Neutral',color:'var(--neutral)'},{key:'casual',label:'Casual',color:'var(--casual)'}];
    var box=$(id);
    if(!box)return;
    if(box.querySelectorAll('.bar-row').length!==rows.length){
        box.innerHTML=rows.map(function(x){return'<div class="bar-row" data-key="'+x.key+'"><span class="bar-label">'+x.label+'</span><div class="bar-track"><div class="bar-fill" style="background:'+x.color+'"></div></div><span class="bar-pct">0%</span></div>';}).join('');
        void box.offsetWidth; // start from empty so the first fill is seen
    }
    rows.forEach(function(x){
        var p=Math.max(0,Math.min(100,Math.round((scores&&scores[x.key]||0)*100)));
        var row=box.querySelector('.bar-row[data-key="'+x.key+'"]');
        row.querySelector('.bar-fill').style.setProperty('--p',p/100);
        var pct=row.querySelector('.bar-pct');
        if(window.ivyCountTo)ivyCountTo(pct,p,'%');else pct.textContent=p+'%';
    });
}
function renderRadar(results){if(typeof Chart==='undefined')return;/* chart library failed to load: keep the translations */var ctx=$('radarChart');if(radarChart)radarChart.destroy();radarChart=new Chart(ctx,{type:'radar',data:{labels:['Formal','Neutral','Casual'],datasets:[{label:'Formal',data:[Math.round((results.formal.style_scores.formal||0)*100),Math.round((results.formal.style_scores.neutral||0)*100),Math.round((results.formal.style_scores.casual||0)*100)],backgroundColor:'rgba(34,211,238,0.1)',borderColor:'#22d3ee',borderWidth:2,pointBackgroundColor:'#22d3ee',pointRadius:3},{label:'Neutral',data:[Math.round((results.neutral.style_scores.formal||0)*100),Math.round((results.neutral.style_scores.neutral||0)*100),Math.round((results.neutral.style_scores.casual||0)*100)],backgroundColor:'rgba(100,116,139,0.1)',borderColor:'#64748b',borderWidth:2,pointBackgroundColor:'#64748b',pointRadius:3},{label:'Casual',data:[Math.round((results.casual.style_scores.formal||0)*100),Math.round((results.casual.style_scores.neutral||0)*100),Math.round((results.casual.style_scores.casual||0)*100)],backgroundColor:'rgba(251,146,60,0.1)',borderColor:'#fb923c',borderWidth:2,pointBackgroundColor:'#fb923c',pointRadius:3}]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{beginAtZero:true,max:100,ticks:{stepSize:25,color:'#3a4a40',backdropColor:'transparent',font:{size:9}},grid:{color:'#1a2420'},angleLines:{color:'#1a2420'},pointLabels:{color:'#8fa89a',font:{size:12,family:'Outfit'}}}},plugins:{legend:{labels:{color:'#8fa89a',font:{size:11,family:'Outfit'},usePointStyle:true,pointStyle:'circle',padding:14}}}}});}

var activeTooltipWord=null;
var tooltipHideTimer=null;
var tooltipOpenedAt=0;
var lastPointerType='mouse';
document.addEventListener('pointerdown',function(e){lastPointerType=e.pointerType||'mouse';},true);

function clearTooltipHide(){
    if(tooltipHideTimer){
        clearTimeout(tooltipHideTimer);
        tooltipHideTimer=null;
    }
}

function hideActiveTooltip(){
    clearTooltipHide();
    if(!activeTooltipWord)return;
    var tooltip=activeTooltipWord.querySelector('.tooltip');
    if(tooltip){
        tooltip.classList.remove('tooltip-visible','tooltip-fixed');
        tooltip.style.top='';
        tooltip.style.bottom='';
        tooltip.style.left='';
        tooltip.style.right='';
        tooltip.style.transform='';
    }
    activeTooltipWord.classList.remove('tooltip-open');
    activeTooltipWord=null;
}

function scheduleTooltipHide(){
    clearTooltipHide();
    tooltipHideTimer=setTimeout(hideActiveTooltip,80);
}

function positionTooltip(wordSpan){
    if(!wordSpan)return;
    var tooltip=wordSpan.querySelector('.tooltip');
    if(!tooltip)return;
    clearTooltipHide();
    if(activeTooltipWord&&activeTooltipWord!==wordSpan){
        hideActiveTooltip();
    }
    if(activeTooltipWord!==wordSpan)tooltipOpenedAt=Date.now();
    activeTooltipWord=wordSpan;
    activeTooltipWord.classList.add('tooltip-open');
    tooltip.classList.add('tooltip-visible');
    tooltip.classList.remove('tooltip-fixed');
    tooltip.style.top='';
    tooltip.style.bottom='calc(100% - 8px)';
    tooltip.style.left='50%';
    tooltip.style.right='auto';
    tooltip.style.transform='translateX(-50%)';
    keepTooltipOnScreen(tooltip);
}

// Nudge an open tooltip so it never runs off the side or top of the screen.
function keepTooltipOnScreen(tooltip){
    var margin=8;
    var rect=tooltip.getBoundingClientRect();
    var shift=0;
    if(rect.left<margin)shift=margin-rect.left;
    else if(rect.right>window.innerWidth-margin)shift=(window.innerWidth-margin)-rect.right;
    if(shift)tooltip.style.transform='translateX(calc(-50% + '+Math.round(shift)+'px))';
    if(rect.top<margin){
        tooltip.style.bottom='auto';
        tooltip.style.top='calc(100% + 8px)';
    }
}

// Tap or click a word to open its details; tap anywhere else to close them.
document.addEventListener('click',function(e){
    if(e.target.closest('.tooltip'))return;
    var wordSpan=e.target.closest('.word-span');
    if(wordSpan){
        // A tap also fires focus and mouseover, which already opened it; only a later tap closes it.
        if(activeTooltipWord===wordSpan&&e.pointerType!=='mouse'&&Date.now()-tooltipOpenedAt>400)hideActiveTooltip();
        else positionTooltip(wordSpan);
        return;
    }
    if(activeTooltipWord)hideActiveTooltip();
});

// Keyboard: focusing a word opens its details, leaving it closes them.
document.addEventListener('focusin',function(e){
    var wordSpan=e.target.closest&&e.target.closest('.word-span');
    if(wordSpan&&e.target===wordSpan)positionTooltip(wordSpan);
});
document.addEventListener('focusout',function(e){
    var wordSpan=e.target.closest&&e.target.closest('.word-span');
    if(wordSpan&&activeTooltipWord===wordSpan&&!wordSpan.contains(e.relatedTarget))scheduleTooltipHide();
});

document.addEventListener('mouseover',function(e){
    var wordSpan=e.target.closest('.word-span');
    if(wordSpan){
        positionTooltip(wordSpan);
        return;
    }
    var tooltip=e.target.closest('.tooltip');
    if(tooltip&&activeTooltipWord&&activeTooltipWord.querySelector('.tooltip')===tooltip){
        clearTooltipHide();
    }
});

document.addEventListener('mouseout',function(e){
    // Touch screens send a fake "mouse left" after every tap; only a tap elsewhere closes details there.
    if(lastPointerType==='touch')return;
    var wordSpan=e.target.closest('.word-span');
    if(wordSpan&&activeTooltipWord===wordSpan){
        scheduleTooltipHide();
        return;
    }
    var tooltip=e.target.closest('.tooltip');
    if(tooltip&&activeTooltipWord&&activeTooltipWord.querySelector('.tooltip')===tooltip){
        scheduleTooltipHide();
    }
});

window.addEventListener('resize',function(){
    document.querySelectorAll('.tooltip').forEach(function(tooltip){
        tooltip.classList.remove('tooltip-visible','tooltip-fixed');
        tooltip.style.top='';
        tooltip.style.bottom='';
        tooltip.style.left='';
        tooltip.style.right='';
        tooltip.style.transform='';
    });
    document.querySelectorAll('.word-span.tooltip-open').forEach(function(wordSpan){
        wordSpan.classList.remove('tooltip-open');
    });
    clearTooltipHide();
    if(activeTooltipWord)positionTooltip(activeTooltipWord);
    syncModeStageHeight();
});

window.addEventListener('scroll',function(){
    if(activeTooltipWord)positionTooltip(activeTooltipWord);
},true);

function setStoryStatus(message,tone){
    var setup=$('storyStatus');
    var reader=$('storyReaderStatus');
    var statusTone=tone||'working';
    [setup,reader].forEach(function(node){
        if(!node)return;
        node.textContent=message||'';
        node.classList.remove('is-working','is-ready','is-error');
        node.classList.add('is-'+statusTone);
    });
}

function persistKaraokePref(on){
    try{localStorage.setItem('ivy-karaoke',on?'1':'0');}catch(e){}
}

function loadKaraokePref(){
    try{
        var stored=localStorage.getItem('ivy-karaoke');
        return stored===null?true:stored==='1';
    }catch(e){
        return true;
    }
}

function setKaraokeToggleState(on){
    var btn=$('storyKaraokeToggle');
    if(!btn)return;
    btn.classList.toggle('is-on',!!on);
    btn.setAttribute('aria-pressed',on?'true':'false');
}

function setKaraokeAvailable(available){
    var btn=$('storyKaraokeToggle');
    if(!btn)return;
    btn.disabled=!available;
    btn.classList.toggle('is-disabled',!available);
    btn.title=available?'Highlight each word as it is spoken':'Word sync is available after word analysis finishes';
}

function maybeAutoPrepareKaraoke(){
    if(!karaokeEnabled||!currentStory||!Array.isArray(currentStory.word_data)||!currentStory.word_data.length)return;
    if(currentStory.audio_url&&Array.isArray(currentStory.timepoints)&&currentStory.timepoints.length)return;
    var player=$('storyAudioPlayer');
    if(player&&!player.paused&&!player.ended)return;
    setStoryTtsButtonsBusy('google',true);
    ensureKaraokeData().finally(function(){
        setStoryTtsButtonsBusy('google',false);
    });
}

function toggleStoryKaraoke(){
    var btn=$('storyKaraokeToggle');
    if(!btn||btn.disabled)return;
    karaokeEnabled=!karaokeEnabled;
    persistKaraokePref(karaokeEnabled);
    setKaraokeToggleState(karaokeEnabled);
    if(karaokeEnabled){
        if(currentStory&&currentStory.timepoints&&currentStory.timepoints.length){
            startKaraokeLoop();
        }else if(currentStory&&Array.isArray(currentStory.word_data)&&currentStory.word_data.length){
            setStoryTtsButtonsBusy('google',true);
            ensureKaraokeData().then(function(ready){
                if(ready){
                    startKaraokeLoop();
                }
            }).finally(function(){
                setStoryTtsButtonsBusy('google',false);
            });
        }
    }else{
        stopKaraokeLoop();
        clearKaraokeHighlights();
    }
}

function clearKaraokeHighlights(){
    document.querySelectorAll('#storyText .word-span.is-speaking,#storyText .word-span.is-spoken,#storyText .story-punct.is-spoken').forEach(function(span){
        span.classList.remove('is-speaking','is-spoken');
    });
    var storyText=$('storyText');
    if(storyText)storyText.classList.remove('karaoke-active');
    karaokeLastSpokenIndex=-1;
}

function refreshKaraokeWordSpans(){
    karaokeWordSpans=[];
    Array.prototype.slice.call(document.querySelectorAll('#storyText .word-span')).forEach(function(span){
        var index=parseInt(span.getAttribute('data-index')||'',10);
        if(!isNaN(index)){
            karaokeWordSpans[index]=span;
        }
    });
}

function forEachKaraokeSpan(callback){
    Array.prototype.slice.call(document.querySelectorAll('#storyText .word-span')).forEach(function(span){
        var index=parseInt(span.getAttribute('data-index')||'',10);
        if(!isNaN(index)){
            callback(span,index);
        }
    });
}

function forEachKaraokePunct(callback){
    Array.prototype.slice.call(document.querySelectorAll('#storyText .story-punct')).forEach(function(span){
        var index=parseInt(span.getAttribute('data-after-index')||'',10);
        if(!isNaN(index)){
            callback(span,index);
        }
    });
}

function setKaraokePunctSpoken(wordIndex,spoken){
    forEachKaraokePunct(function(span,index){
        if(index===wordIndex){
            span.classList.toggle('is-spoken',!!spoken);
        }
    });
}

function findTimepointIndex(currentTime,timepoints){
    if(!timepoints||!timepoints.length||currentTime<timepoints[0].time)return -1;
    var lo=0,hi=timepoints.length-1,answer=-1;
    while(lo<=hi){
        var mid=(lo+hi)>>1;
        if(timepoints[mid].time<=currentTime){
            answer=mid;
            lo=mid+1;
        }else{
            hi=mid-1;
        }
    }
    return answer;
}

function syncKaraokeHighlight(){
    if(!karaokeEnabled||!currentStory||!currentStory.timepoints||!currentStory.timepoints.length)return;
    refreshKaraokeWordSpans();
    var player=$('storyAudioPlayer');
    if(!player)return;
    var timepointIndex=findTimepointIndex(player.currentTime||0,currentStory.timepoints);
    var wordIndex=timepointIndex>=0?currentStory.timepoints[timepointIndex].index:-1;
    forEachKaraokeSpan(function(span,index){
        span.classList.remove('is-speaking');
        span.classList.toggle('is-spoken',wordIndex>=0&&index<wordIndex);
    });
    forEachKaraokePunct(function(span,index){
        span.classList.toggle('is-spoken',wordIndex>=0&&index<wordIndex);
    });
    if(wordIndex>=0&&karaokeWordSpans[wordIndex]){
        karaokeWordSpans[wordIndex].classList.add('is-speaking');
        karaokeWordSpans[wordIndex].classList.remove('is-spoken');
    }
    karaokeLastSpokenIndex=wordIndex;
}

function karaokeTick(){
    if(!karaokeEnabled){
        karaokeRaf=null;
        return;
    }
    var player=$('storyAudioPlayer');
    if(!player||!currentStory||!currentStory.timepoints||!currentStory.timepoints.length){
        karaokeRaf=null;
        return;
    }
    if(!player.paused&&!player.ended){
        var timepointIndex=findTimepointIndex(player.currentTime||0,currentStory.timepoints);
        var wordIndex=timepointIndex>=0?currentStory.timepoints[timepointIndex].index:-1;
        if(wordIndex!==karaokeLastSpokenIndex){
            if(karaokeLastSpokenIndex>=0&&karaokeWordSpans[karaokeLastSpokenIndex]){
                karaokeWordSpans[karaokeLastSpokenIndex].classList.remove('is-speaking');
                karaokeWordSpans[karaokeLastSpokenIndex].classList.add('is-spoken');
                setKaraokePunctSpoken(karaokeLastSpokenIndex,true);
            }
            if(wordIndex>=0&&wordIndex<karaokeLastSpokenIndex){
                syncKaraokeHighlight();
            }else if(wordIndex>=0&&karaokeWordSpans[wordIndex]){
                for(var i=karaokeLastSpokenIndex+1;i<wordIndex;i++){
                    if(karaokeWordSpans[i]){
                        karaokeWordSpans[i].classList.remove('is-speaking');
                        karaokeWordSpans[i].classList.add('is-spoken');
                        setKaraokePunctSpoken(i,true);
                    }
                }
                karaokeWordSpans[wordIndex].classList.add('is-speaking');
                karaokeWordSpans[wordIndex].classList.remove('is-spoken');
                setKaraokePunctSpoken(wordIndex,false);
                karaokeLastSpokenIndex=wordIndex;
            }
        }
    }
    karaokeRaf=requestAnimationFrame(karaokeTick);
}

function startKaraokeLoop(){
    stopKaraokeLoop();
    refreshKaraokeWordSpans();
    var storyText=$('storyText');
    if(storyText)storyText.classList.add('karaoke-active');
    syncKaraokeHighlight();
    karaokeRaf=requestAnimationFrame(karaokeTick);
}

function stopKaraokeLoop(){
    if(karaokeRaf){
        cancelAnimationFrame(karaokeRaf);
        karaokeRaf=null;
    }
}

function normalizeKaraokeTimepoints(timepoints){
    if(!Array.isArray(timepoints))return [];
    return timepoints.map(function(item){
        return {
            index:parseInt(item&&item.index,10),
            time:parseFloat(item&&item.time),
            sync_version:item&&item.sync_version
        };
    }).filter(function(item){
        return !isNaN(item.index)&&isFinite(item.time)&&item.index>=0&&item.time>=0;
    }).sort(function(a,b){
        return a.time-b.time;
    });
}

function applyKaraokePayload(payload){
    if(!payload||!payload.audio_b64||!Array.isArray(payload.timepoints)||!payload.timepoints.length)return false;
    var normalizedTimepoints=normalizeKaraokeTimepoints(payload.timepoints);
    if(!normalizedTimepoints.length)return false;
    var binary=atob(payload.audio_b64);
    var bytes=new Uint8Array(binary.length);
    for(var i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
    var blob=new Blob([bytes],{type:'audio/mpeg'});
    var oldAudioUrl=currentStoryAudioUrl;
    currentStoryAudioUrl=URL.createObjectURL(blob);
    currentStoryNarrationB64=payload.audio_b64;
    if(currentStory){
        currentStory.audio_url=currentStoryAudioUrl;
        currentStory.timepoints=normalizedTimepoints;
        currentStory.has_audio=true;
        currentStory.has_narration=true;
    }
    var player=$('storyAudioPlayer');
    if(player){
        player.src=currentStoryAudioUrl;
        player.load();
        syncStoryAudioUI();
    }
    if(oldAudioUrl&&oldAudioUrl!==currentStoryAudioUrl){
        URL.revokeObjectURL(oldAudioUrl);
    }
    return true;
}

async function ensureKaraokeData(){
    if(!currentStory||!Array.isArray(currentStory.word_data)||!currentStory.word_data.length)return false;
    if(currentStory.audio_url&&Array.isArray(currentStory.timepoints)&&currentStory.timepoints.length)return true;
    if(karaokeDataPromise)return await karaokeDataPromise;
    var storyAtStart=currentStory;
    var token=++karaokeFetchToken;
    var promise=(async function(){
        try{
            if(storyAtStart.id&&storyAtStart.has_narration){
                var cached=await fetch('/api/stories/'+storyAtStart.id+'/narration');
                if(token!==karaokeFetchToken)return false;
                if(cached.ok){
                    var cachedPayload=await cached.json();
                    if(token!==karaokeFetchToken||currentStory!==storyAtStart)return false;
                    if(applyKaraokePayload(cachedPayload))return true;
                }
            }
            setStoryStatus('Preparing word sync…','working');
            var response=await fetch('/api/stories/tts-marked',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({
                    story_text:storyAtStart.story_text||'',
                    word_data:storyAtStart.word_data||[],
                    language:storyAtStart.target_lang||$('storyTargetLang').value,
                    story_id:storyAtStart.id||null
                })
            });
            if(token!==karaokeFetchToken)return false;
            var payload=await response.json();
            if(!response.ok||payload.error)throw new Error(payload.error||'Could not prepare word sync.');
            if(token!==karaokeFetchToken||currentStory!==storyAtStart)return false;
            if(!applyKaraokePayload(payload))throw new Error('Could not prepare word sync.');
            setStoryStatus('Narration with word sync ready.','ready');
            return true;
        }catch(e){
            if(token===karaokeFetchToken&&currentStory===storyAtStart){
                setStoryStatus(e.message||'Could not prepare word sync.','error');
            }
            return false;
        }
    })();
    karaokeDataPromise=promise;
    try{
        return await promise;
    }finally{
        if(karaokeDataPromise===promise){
            karaokeDataPromise=null;
        }
    }
}

async function playStoryAudio(provider){
    if(!currentStory||!(currentStory.story_text||'').trim()){
        setStoryStatus('Generate or open a story before testing narration.','error');
        return;
    }

    var player=$('storyAudioPlayer');
    if(player){
        player.muted=false;
        player.volume=1;
    }
    updateStoryAudioPlaybackRate();
    if(player&&!player.paused&&!player.ended){
        player.pause();
        stopKaraokeLoop();
        syncStoryAudioUI();
        return;
    }

    if(karaokeEnabled&&Array.isArray(currentStory.word_data)&&currentStory.word_data.length){
        var karaokeReady=true;
        if(!currentStory.audio_url||!Array.isArray(currentStory.timepoints)||!currentStory.timepoints.length){
            setStoryTtsButtonsBusy(provider,true);
            try{
                karaokeReady=await ensureKaraokeData();
            }finally{
                setStoryTtsButtonsBusy(provider,false);
            }
        }
        if(karaokeReady){
            if(!sameAudioSource(player,currentStory.audio_url)){
                player.src=currentStory.audio_url;
                player.load();
                syncStoryAudioUI();
            }
            try{
                await player.play();
                startKaraokeLoop();
                syncStoryAudioUI();
                setStoryStatus('Narration with word sync ready.','ready');
            }catch(e){
                syncStoryAudioUI();
                setStoryStatus('Narration is ready. Press play again to start audio.','ready');
            }
            return;
        }
    }

    if(currentStory.audio_url){
        if(!sameAudioSource(player,currentStory.audio_url)){
            player.src=currentStory.audio_url;
            player.load();
            syncStoryAudioUI();
        }
        try{
            await player.play();
            if(karaokeEnabled&&currentStory.timepoints&&currentStory.timepoints.length)startKaraokeLoop();
            syncStoryAudioUI();
            setStoryStatus('Narration ready.','ready');
            return;
        }catch(e){
            syncStoryAudioUI();
            setStoryStatus('Narration is ready. Press play again to start audio.','ready');
            return;
        }
    }

    setStoryTtsButtonsBusy(provider,true);
    setStoryStatus('Creating Google narration…','working');
    try{
        var r=await fetch('/api/stories/tts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:provider,text:currentStory.story_text,language:currentStory.target_lang||$('storyTargetLang').value,story_id:currentStory.id||null})});
        if(!r.ok){
            var errorMessage='Could not create narration.';
            try{
                var d=await r.json();
                errorMessage=d.error||errorMessage;
            }catch(e){}
            throw new Error(errorMessage);
        }
        var blob=await r.blob();
        resetStoryAudioPlayer();
        currentStoryAudioUrl=URL.createObjectURL(blob);
        currentStory.audio_url=currentStoryAudioUrl;
        if(currentStory.id)currentStory.has_audio=true;
        player.src=currentStoryAudioUrl;
        player.load();
        updateStoryAudioPlaybackRate();
        try{
            await player.play();
            setStoryStatus('Narration ready.','ready');
        }catch(e){
            setStoryStatus('Narration is ready. Press play again to start audio.','ready');
        }
        syncStoryAudioUI();
    }catch(e){
        setStoryStatus(e.message||'Could not create narration.','error');
    }finally{
        setStoryTtsButtonsBusy(provider,false);
        syncStoryAudioUI();
    }
}

function setStoryGeneratingState(active){
    var btn=$('generateStoryBtn');
    if(!btn)return;
    if(active){
        btn.disabled=true;
        btn.classList.add('loading');
        btn.innerHTML='Generating <span class="loading-dots"><span></span><span></span><span></span></span>';
        storyFactIndex=Math.floor(Math.random()*storyFunFacts.length);
        setStoryStatus(storyFunFacts[storyFactIndex],'working');
        clearInterval(storyFactTimer);
        storyFactTimer=setInterval(function(){
            storyFactIndex=(storyFactIndex+1)%storyFunFacts.length;
            setStoryStatus(storyFunFacts[storyFactIndex],'working');
        },3500);
    }else{
        clearInterval(storyFactTimer);
        storyFactTimer=null;
        btn.disabled=false;
        btn.classList.remove('loading');
        btn.textContent='Generate story';
    }
}

function resetStoryAudioPlayer(){
    var player=$('storyAudioPlayer');
    if(!player)return;
    stopKaraokeLoop();
    clearKaraokeHighlights();
    player.pause();
    player.removeAttribute('src');
    player.load();
    syncStoryAudioUI();
    if(currentStoryAudioUrl){
        URL.revokeObjectURL(currentStoryAudioUrl);
        currentStoryAudioUrl='';
    }
    currentStoryNarrationB64='';
}

function updateStoryAudioPlaybackRate(){
    var player=$('storyAudioPlayer');
    var selector=$('storyPlaybackRate');
    if(!player||!selector)return;
    player.playbackRate=parseFloat(selector.value||'1')||1;
}

  function syncStoryAudioUI(){
      var player=$('storyAudioPlayer');
      var progress=$('storyAudioProgress');
      var playBtn=$('googleTtsBtn');
      if(!player||!progress||!playBtn)return;
      var duration=player.duration||0;
      var current=player.currentTime||0;
      var pct=duration>0?(current/duration)*100:0;
      progress.value=String(pct);
      progress.style.setProperty('--progress',pct.toFixed(2)+'%');
      var isPlaying=!player.paused&&!player.ended;
      playBtn.classList.toggle('is-playing',isPlaying);
      playBtn.setAttribute('aria-label',isPlaying?'Pause audio':'Play audio');
      playBtn.setAttribute('title',isPlaying?'Pause audio':'Play audio');
  }

function seekStoryAudio(delta){
    var player=$('storyAudioPlayer');
    if(!player||!player.src)return;
    player.currentTime=Math.max(0,Math.min((player.duration||0), (player.currentTime||0)+delta));
    syncStoryAudioUI();
}

function scrubStoryAudio(value){
    var player=$('storyAudioPlayer');
    var progress=$('storyAudioProgress');
    if(!player||!progress||!player.src)return;
    var pct=parseFloat(value||'0')||0;
    progress.style.setProperty('--progress',pct.toFixed(2)+'%');
    if(player.duration){
        player.currentTime=(pct/100)*player.duration;
    }
    syncStoryAudioUI();
}

  function setStoryTtsButtonsBusy(provider,busy){
      var googleBtn=$('googleTtsBtn');
      if(!googleBtn)return;
      googleBtn.disabled=busy;
      googleBtn.classList.remove('is-playing');
      googleBtn.setAttribute('aria-label',busy?'Loading Google voice':'Play audio');
      googleBtn.setAttribute('title',busy?'Loading Google voice':'Play audio');
  }

function showStorySetup(){
    storyReaderOpen=false;
    $('storyShell').classList.remove('reader-open');
    resetStoryAudioPlayer();
    setKaraokeAvailable(false);
    setStoryStatus(currentStory?'Adjust the options, then generate a new story.':'Choose a level and theme, then generate.','ready');
    updateStoryShellHeight();
    requestAnimationFrame(syncModeStageHeight);
}

async function generateStory(){
    if(isGeneratingStory)return;
    isGeneratingStory=true;
    $('saveStoryBtn').disabled=true;
    saveStoryPreferences();
    setStoryGeneratingState(true);
    try{
        var payload={
            target_lang:$('storyTargetLang').value,
            support_lang:$('storySupportLang').value,
            cefr_level:$('storyLevel').value,
            theme:$('storyTheme').value.trim()||'daily life',
            length_label:$('storyLength').value,
            style:$('storyStyle').value,
            variation_id:Date.now()+'-'+Math.random().toString(36).slice(2),
            personalize:isPersonalizeOn()
        };
        var d=null;
        while(isGeneratingStory){
            var r=await fetch('/api/stories/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            d=await r.json();
            if(!d.error)break;
            var errorText=String(d.error||'').toLowerCase();
            if(errorText.indexOf('not configured')!==-1||errorText.indexOf('api key')!==-1){
                throw new Error(d.error);
            }
            setStoryStatus('Gemini is busy, so Ivy is still trying. '+storyFunFacts[storyFactIndex],'working');
            await new Promise(function(resolve){setTimeout(resolve,3500);});
        }
        renderStoryContent(d);
        openStoryReader();
        var readyMessage=d.personalized?'Tailored to your vocabulary. Hover words to inspect and save.':'Story ready. Hover words to inspect and save vocabulary.';
        if((d.word_data||[]).length>0){
            setStoryStatus(readyMessage,'ready');
        }else{
            setStoryStatus(d.personalized?'Tailored to your vocabulary. Adding hoverable word analysis in the background…':'Story ready. Adding hoverable word analysis in the background…','working');
            startStoryWordAnalysis(d,readyMessage);
        }
    }catch(e){
        currentStory=null;
        showStorySetup();
        setStoryStatus(e.message||'Could not generate a story yet.','error');
    }finally{
        isGeneratingStory=false;
        setStoryGeneratingState(false);
        updateSaveStoryButton();
        requestAnimationFrame(syncModeStageHeight);
    }
}

async function openSavedStory(storyId){
    try{
        setStoryStatus('Opening saved story…','working');
        var r=await fetch('/api/stories/'+storyId);
        var d=await r.json();
        if(d.error)throw new Error(d.error);
        var story=d.story||{};
        story.comprehension_questions=safeJsonArray(story.comprehension_json);
        story.focus_vocabulary=safeJsonArray(story.focus_vocab_json);
        story.word_data=enrichWordDataWithFocus(safeJsonArray(story.word_data_json),story.focus_vocabulary);
        story.saved=true;
        renderStoryContent(story);
        setMode('stories');
        openStoryReader();
        applyCachedStoryAudio(story);
        if(story.story_text&&story.word_data.length===0){
            setStoryStatus('Story loaded. Adding hoverable word analysis in the background…','working');
            startStoryWordAnalysis(story,'Story ready. Hover words to inspect and save vocabulary.');
        }else{
            setStoryStatus('Loaded from your saved stories.','ready');
        }
    }catch(e){
        setStoryStatus(e.message||'Could not open saved story.','error');
    }
}

setStoryStatus('Choose a level and theme, then generate.','ready');
var storyAudioPlayer=$('storyAudioPlayer');
if(storyAudioPlayer){
    ['timeupdate','loadedmetadata','play','pause','ended'].forEach(function(eventName){
        storyAudioPlayer.addEventListener(eventName,syncStoryAudioUI);
    });
    storyAudioPlayer.addEventListener('play',function(){
        if(karaokeEnabled&&currentStory&&currentStory.timepoints&&currentStory.timepoints.length){
            startKaraokeLoop();
        }
    });
    storyAudioPlayer.addEventListener('pause',function(){
        stopKaraokeLoop();
    });
    storyAudioPlayer.addEventListener('ended',function(){
        stopKaraokeLoop();
        if(karaokeEnabled){
            refreshKaraokeWordSpans();
            forEachKaraokeSpan(function(span){
                span.classList.remove('is-speaking');
                span.classList.add('is-spoken');
            });
            forEachKaraokePunct(function(span){
                span.classList.add('is-spoken');
            });
        }
    });
    storyAudioPlayer.addEventListener('seeked',syncKaraokeHighlight);
}

karaokeEnabled=loadKaraokePref();
setKaraokeToggleState(karaokeEnabled);
setKaraokeAvailable(false);

document.addEventListener('keydown',function(e){
    if(handlePracticeKeyboard(e))return;
    var target=e.target;
    var isEditable=isKeyboardEditableTarget(target);
    if(e.code==='Space'&&!isEditable&&currentMode==='stories'&&currentStory){
        e.preventDefault();
        playStoryAudio('google');
        return;
    }
    if(e.key==='Escape'){
        var ivyPanel=$('ivyExplanationPanel');
        if(ivyPanel&&ivyPanel.classList.contains('open')){
            closeIvyPanel();
            return;
        }
        closeAuth();closeVocab();closeDropdown();
    }
});
initTheme();
initStoryPreferences();
checkAuth();
checkRestyleMode();
requestAnimationFrame(syncModeStageHeight);

// sets.html deep-links here with #flashcards?set=N&lang=tr.
(function applyDeepLink(){
    var hash=(window.location.hash||'').replace(/^#/,'');
    if(!hash)return;
    var qIndex=hash.indexOf('?');
    var route=qIndex===-1?hash:hash.slice(0,qIndex);
    var query=qIndex===-1?'':hash.slice(qIndex+1);
    var params={};
    query.split('&').forEach(function(kv){
        if(!kv)return;
        var pair=kv.split('=');
        params[decodeURIComponent(pair[0])]=decodeURIComponent(pair[1]||'');
    });
    if(route==='flashcards'){
        if(params.lang)currentFlashcardLang=params.lang;
        if(params.set){
            var sid=parseInt(params.set,10);
            if(!isNaN(sid))currentFlashcardSetId=sid;
        }
        setMode('flashcards');
    }else if(['compare','stories','practice'].indexOf(route)!==-1){
        setMode(route);
    }
})();
