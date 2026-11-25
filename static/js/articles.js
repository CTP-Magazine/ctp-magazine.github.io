
      /* Latest Articles — reads articles.json at runtime, renders cards newest
         first, 40 at a time, with a title search over the loaded cards. */
      (function () {
        var PAGE = 40;
        var listEl = document.getElementById('articleList');
        var countEl = document.getElementById('statusArticleCount');
        /* Pages without the Latest Articles section (e.g. /legal.html) have
           no article list — but the Magazine Status module still shows the
           article count. Fetch just for that, then stop. */
        if (!listEl) {
          if (countEl) {
            fetch('articles.json').then(function (r) { return r.json(); }).then(function (data) {
              var arr = Array.isArray(data) ? data : (data.articles || data.items || []);
              countEl.textContent = arr.length + ' articles in the current edition';
            }).catch(function () {});
          }
          return;
        }
        var moreBtn = document.getElementById('artMore');
        var searchEl = document.getElementById('artSearch');
        var topicMenu = document.getElementById('topicMenu');
        var tagCloud = document.getElementById('tagCloud');
        var topicLine = document.getElementById('artTopicLine');
        var all = [];
        var shown = 0;
        /* Active topic filter ('' = all topics). Each article carries a
           `topic` from aggregate.py, so a topic returns exactly the
           stories from its own feeds — like MSN, each topic shows
           different stories. */
        var activeTopic = '';

        function field(a, names) {
          for (var i = 0; i < names.length; i++) {
            if (a[names[i]]) return a[names[i]];
          }
          return '';
        }
        /* Front-door cap: arXiv preprints are 103 of 271 articles, so the
           default All Topics view would read like a pre-print dump. Cap
           arXiv at 4 cards in All Topics only; topic views are uncapped
           (a reader who chooses Physics wants preprints). */
        var ARXIV_CAP = 4;
        function isArxiv(a) {
          var s = String(field(a, ['feed', 'publisher', 'source']) || '').toLowerCase();
          return s.indexOf('arxiv') === 0;
        }
        function filtered() {
          var items = all;
          if (activeTopic) {
            items = items.filter(function (a) {
              return field(a, ['topic']) === activeTopic;
            });
          }
          var q = (searchEl.value || '').toLowerCase().trim();
          if (q) {
            items = items.filter(function (a) {
              return String(field(a, ['title'])).toLowerCase().indexOf(q) > -1;
            });
          }
          if (!activeTopic) {
            var n = 0;
            items = items.filter(function (a) {
              if (!isArxiv(a)) return true;
              if (n < ARXIV_CAP) { n++; return true; }
              return false;
            });
          }
          return items;
        }
        function render() {
          var items = filtered();
          var slice = items.slice(0, shown);
          listEl.innerHTML = '';
          if (topicLine) {
            topicLine.textContent = activeTopic
              ? 'Showing ' + activeTopic + ' — ' + items.length + ' article' + (items.length === 1 ? '' : 's')
              : 'Showing all topics — ' + items.length + ' articles';
          }
          if (!items.length) {
            var p = document.createElement('p');
            p.className = 'art-note';
            p.textContent = all.length
              ? (activeTopic ? 'No articles in ' + activeTopic + ' yet — check back soon.' : 'No articles match that search.')
              : 'No articles yet — check back soon.';
            listEl.appendChild(p);
          }
          slice.forEach(function (a) {
            var url = field(a, ['url', 'link']);
            var card = document.createElement('article');
            card.className = 'article-card';
            var meta = document.createElement('div');
            meta.className = 'a-meta';
            var src = field(a, ['source', 'feed', 'site']);
            var date = field(a, ['date', 'published', 'pubDate', 'updated']);
            var dateTxt = '';
            if (date) {
              var d = new Date(date);
              dateTxt = isNaN(d.getTime()) ? String(date) : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
            }
            meta.textContent = [src, dateTxt].filter(Boolean).join(' · ');
            card.appendChild(meta);
            /* Thumbnail — only when the article carries a cleared image URL
               (aggregate.py blanks the image field for uncleared sources,
               so a present image is always NASA public domain, ESO CC BY
               4.0, or a CC-BY journal figure). Text-only otherwise. */
            var thumb = field(a, ['image']);
            if (thumb && url) {
              var tlink = document.createElement('a');
              tlink.className = 'a-thumb';
              tlink.href = url; tlink.target = '_blank'; tlink.rel = 'noopener';
              var timg = document.createElement('img');
              timg.src = thumb; timg.alt = field(a, ['title']) || '';
              timg.loading = 'lazy';
              var cred = field(a, ['image_credit']);
              if (cred) timg.title = 'Image: ' + cred;
              timg.onerror = function(){ tlink.style.display = 'none'; };
              tlink.appendChild(timg);
              card.appendChild(tlink);
            }
            var h = document.createElement('h3');
            if (url) {
              var link = document.createElement('a');
              link.href = url; link.target = '_blank'; link.rel = 'noopener';
              link.textContent = field(a, ['title']) || url;
              h.appendChild(link);
            } else {
              h.textContent = field(a, ['title']);
            }
            card.appendChild(h);
            var ex = field(a, ['excerpt', 'summary', 'description']);
            if (ex) {
              /* Excerpts arrive paragraph-separated ("\n\n") from the
                 aggregator — render each paragraph as its own <p> so a
                 card is never one unformatted wall. */
              String(ex).split(/\n\n+/).forEach(function (para) {
                para = para.trim();
                if (!para) return;
                var p = document.createElement('p');
                p.textContent = para;
                card.appendChild(p);
              });
            }
            if (url) {
              var more = document.createElement('a');
              more.className = 'a-more';
              more.href = url; more.target = '_blank'; more.rel = 'noopener';
              more.textContent = 'Read more at ' + (src || 'the original') + ' ↗';
              card.appendChild(more);
            }
            listEl.appendChild(card);
          });
          moreBtn.style.display = items.length > shown ? '' : 'none';
        }
        moreBtn.addEventListener('click', function () { shown += PAGE; render(); });
        searchEl.addEventListener('input', function () { clearSearchTagHighlight(); shown = PAGE; render(); });
        /* Topic filter — clicking a topic shows only that topic's stories
           (from the already-loaded articles.json; no new fetch). The
           link's href="#latest" still scrolls to the list; the handler
           only sets the filter and highlights the active topic. */
        /* Keep the Topics menu and the Tags cloud in step: whichever one
           the reader clicks, both show the same active topic. */
        function syncTopicHighlight() {
          var menus = [topicMenu, tagCloud];
          for (var m = 0; m < menus.length; m++) {
            if (!menus[m]) continue;
            var links = menus[m].querySelectorAll('a[data-topic]');
            for (var i = 0; i < links.length; i++) {
              links[i].classList.toggle('is-active', (links[i].getAttribute('data-topic') || '') === activeTopic);
            }
          }
        }
        function clearSearchTagHighlight() {
          if (!tagCloud) return;
          var links = tagCloud.querySelectorAll('a[data-search]');
          for (var i = 0; i < links.length; i++) {
            links[i].classList.remove('is-active');
          }
        }
        if (topicMenu) {
          topicMenu.addEventListener('click', function (ev) {
            var a = ev.target.closest ? ev.target.closest('a[data-topic]') : null;
            if (!a) return;
            activeTopic = a.getAttribute('data-topic') || '';
            syncTopicHighlight();
            clearSearchTagHighlight();
            shown = PAGE;
            render();
          });
        }
        /* Tags cloud — a topic tag works exactly like the Topics menu; a
           keyword tag puts that word in the title search box and filters
           by it. Either way the link's href="#latest" scrolls to the list. */
        if (tagCloud) {
          tagCloud.addEventListener('click', function (ev) {
            var a = ev.target.closest ? ev.target.closest('a') : null;
            if (!a) return;
            if (a.hasAttribute('data-topic')) {
              activeTopic = a.getAttribute('data-topic') || '';
              syncTopicHighlight();
              clearSearchTagHighlight();
            } else if (a.hasAttribute('data-search')) {
              activeTopic = '';
              searchEl.value = a.getAttribute('data-search') || '';
              syncTopicHighlight();
              clearSearchTagHighlight();
              a.classList.add('is-active');
            } else {
              return;
            }
            shown = PAGE;
            render();
          });
        }

        fetch('articles.json')
          .then(function (r) { if (!r.ok) throw new Error('articles'); return r.json(); })
          .then(function (data) {
            var arr = Array.isArray(data) ? data : (data.articles || data.items || []);
            all = arr.slice().sort(function (a, b) {
              var da = new Date(field(a, ['date', 'published', 'pubDate', 'updated']) || 0).getTime() || 0;
              var db = new Date(field(b, ['date', 'published', 'pubDate', 'updated']) || 0).getTime() || 0;
              return db - da;
            });
            shown = PAGE;
            if (countEl) countEl.textContent = all.length + ' articles in the current edition';
            render();
          })
          .catch(function () {
            listEl.innerHTML = '';
            var p = document.createElement('p');
            p.className = 'art-note';
            p.textContent = 'The latest articles are loading — please refresh in a moment.';
            listEl.appendChild(p);
            if (countEl) countEl.textContent = 'Loading…';
          });
      })();
    