// === Reaper UI Controller ===
// Injected by backend. Reads paper data from <script id="reaper-data">

(function() {
    'use strict';

    var paperId = '', terms = {};
    var dataEl = document.getElementById('reaper-data');
    if (dataEl) {
        try { var d = JSON.parse(dataEl.textContent); paperId = d.paper_id || ''; terms = d.terms || {}; }
        catch(e) {}
    }
    var zhVisible = true;

    // --- Toolbar ---
    (function() {
        var bar = document.createElement('div');
        bar.id = 'reaper-toolbar';
        bar.innerHTML =
            '<button id="reaper-toggle-btn" class="active">隐藏翻译</button>' +
            '<button id="reaper-term-btn">📖 术语</button>';
        document.body.appendChild(bar);
        document.getElementById('reaper-toggle-btn').addEventListener('click', function() {
            zhVisible = !zhVisible;
            var btn = document.getElementById('reaper-toggle-btn');
            document.querySelectorAll('[data-reaper-zh]').forEach(function(w) {
                w.classList.toggle('hidden', !zhVisible);
            });
            btn.textContent = zhVisible ? '隐藏翻译' : '显示翻译';
            btn.classList.toggle('active', zhVisible);
        });
        document.getElementById('reaper-term-btn').addEventListener('click', function() {
            document.getElementById('reaper-term-panel').classList.toggle('show');
            if (document.getElementById('reaper-term-panel').classList.contains('show')) renderTerms();
        });
    })();

    // --- Term panel ---
    (function() {
        var panel = document.createElement('div');
        panel.id = 'reaper-term-panel';
        panel.innerHTML =
            '<h3>术语字典</h3>' +
            '<div id="reaper-term-list"></div>' +
            '<div class="reaper-add-term">' +
            '<input id="reaper-new-en" placeholder="英文术语">' +
            '<input id="reaper-new-zh" placeholder="中文翻译">' +
            '<button id="reaper-add-btn">+ 添加</button>' +
            '</div>' +
            '<div style="margin-top:10px">' +
            '<button id="reaper-save-btn" style="background:#0f3460;color:#fff;border:none;padding:5px 12px;border-radius:4px;cursor:pointer;">💾 保存</button>' +
            '</div>';
        document.body.appendChild(panel);
        document.getElementById('reaper-add-btn').addEventListener('click', addTerm);
        document.getElementById('reaper-save-btn').addEventListener('click', saveTerms);
    })();

    function renderTerms() {
        var list = document.getElementById('reaper-term-list');
        if (!list) return;
        list.innerHTML = Object.entries(terms).sort().map(function(e) {
            return '<div class="reaper-term-row">' +
                '<input value="' + e[0] + '" data-old="' + e[0] + '" class="term-en" size="14">' +
                '<span>→</span>' +
                '<input value="' + e[1] + '" class="term-zh" size="14">' +
                '<button class="del-btn" data-en="' + e[0] + '">✕</button>' +
                '</div>';
        }).join('');
        document.querySelectorAll('.del-btn').forEach(function(b) {
            b.addEventListener('click', function() { deleteTerm(this.dataset.en); });
        });
    }

    function addTerm() {
        var en = document.getElementById('reaper-new-en').value.trim();
        var zh = document.getElementById('reaper-new-zh').value.trim();
        if (!en || !zh) return;
        terms[en] = zh;
        document.getElementById('reaper-new-en').value = '';
        document.getElementById('reaper-new-zh').value = '';
        renderTerms();
    }

    function deleteTerm(en) { delete terms[en]; renderTerms(); }

    function saveTerms() {
        document.querySelectorAll('.reaper-term-row').forEach(function(row) {
            var enInput = row.querySelector('.term-en'), zhInput = row.querySelector('.term-zh');
            var oldEn = enInput.dataset.old;
            var newEn = enInput.value.trim(), newZh = zhInput.value.trim();
            if (newEn !== oldEn) delete terms[oldEn];
            if (newEn && newZh) terms[newEn] = newZh;
        });
        renderTerms();
        fetch('/api/terms', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({paper_id: paperId, terms: terms})
        }).catch(function() {});
        alert('术语已保存');
    }
})();
