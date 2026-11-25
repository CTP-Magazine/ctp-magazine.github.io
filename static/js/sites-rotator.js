
      /* CTPVerse Sites random rotator — picks a random sister site every 5s,
         never the one currently showing; plain static swap, no fade. */
      (function () {
        var sites = [
          { name: "CTPVerse Dashboard", href: "https://ctpverse.github.io/", img: "https://ctpverse.github.io/images/branding/ctpverse-org-avatar.jpg" },
          { name: "CTP-EOS", href: "https://ctp-eos.github.io/", img: "https://ctp-eos.github.io/assets/branding/ctp-eos-triangle-logo.jpg" },
          { name: "FIN-DSP", href: "https://fin-dsp.github.io/", img: "https://fin-dsp.github.io/assets/branding/findsp-logo-200x200.jpg" },
          { name: "CTP Music Portal", href: "https://ctp-music.github.io/", img: "https://ctp-music.github.io/assets/branding/ctp-music-org-avatar.jpg" },
          { name: "CTP Space Systems", href: "https://ctp-space-systems.github.io/", img: "https://ctp-space-systems.github.io/assets/branding/ctp-space-systems-org-avatar.jpg" },
          { name: "CTP-PSY", href: "https://ctp-psy.github.io/", img: "https://ctp-psy.github.io/assets/branding/ctp-psy-org-avatar.jpg" }
        ];
        var link = document.getElementById("ctpsitesLink");
        var img = document.getElementById("ctpsitesImg");
        if (!link || !img) return;
        var idx = 0;
        function show(i) {
          idx = i;
          var s = sites[i];
          img.src = s.img;
          img.alt = s.name;
          link.href = s.href;
          link.title = s.name + " — visit the site";
          link.setAttribute("aria-label", s.name);
        }
        function randomNext() {
          if (document.hidden) return;
          if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
          var n = idx;
          while (n === idx) { n = Math.floor(Math.random() * sites.length); }
          show(n);
        }
        setInterval(randomNext, 5000);
      })();
    