document.addEventListener("DOMContentLoaded",function(){
    var bar = document.createElement("div");
    bar.className = "reaper-toolbar";

    var tocBtn = document.createElement("button");
    tocBtn.innerHTML = "\u2630";
    tocBtn.title = "Toggle TOC";
    bar.appendChild(tocBtn);

    var themeBtn = document.createElement("button");
    themeBtn.innerHTML = "\u263E";
    themeBtn.title = "Toggle dark/light mode";
    bar.appendChild(themeBtn);

    var tlBtn = document.createElement("button");
    tlBtn.id = "reaper-translation-btn";
    tlBtn.title = "Toggle translation on/off";
    bar.appendChild(tlBtn);

    // Source toggle button (added by reaper-source-toggle.js logic)
    var srcBtn = document.createElement("button");
    srcBtn.id = "reaper-source-btn";
    srcBtn.innerHTML = "\u25CE";
    srcBtn.title = "Switch to CDN";
    srcBtn.onclick = function(){ if(window.toggleReaperSource) toggleReaperSource(); };
    bar.appendChild(srcBtn);

    document.body.insertBefore(bar, document.body.firstChild);

    var tocOpen = false;
    tocBtn.onclick = function(){
        tocOpen = !tocOpen;
        if(tocOpen){
            document.body.classList.add("toc-open");
            tocBtn.classList.add("active");
        }else{
            document.body.classList.remove("toc-open");
            tocBtn.classList.remove("active");
        }
    };

    var dark = localStorage.getItem("reaper-theme") === "dark";
    if(dark) document.documentElement.setAttribute("data-theme", "dark");
    themeBtn.onclick = function(){
        dark = !dark;
        if(dark){
            document.documentElement.setAttribute("data-theme", "dark");
            localStorage.setItem("reaper-theme", "dark");
        }else{
            document.documentElement.removeAttribute("data-theme");
            localStorage.setItem("reaper-theme", "light");
        }
    };

    // Translation on/off toggle
    var translationOn = localStorage.getItem("reaper-translation") !== "off";
    if(!translationOn) document.body.classList.add("translation-off");
    tlBtn.textContent = translationOn ? "\u4E2D" : "En";
    tlBtn.classList.toggle("active", translationOn);
    tlBtn.onclick = function(){
        translationOn = !translationOn;
        document.body.classList.toggle("translation-off", !translationOn);
        tlBtn.classList.toggle("active", translationOn);
        tlBtn.textContent = translationOn ? "\u4E2D" : "En";
        localStorage.setItem("reaper-translation", translationOn ? "on" : "off");
    };

    // TOC subtree toggle (click on toggle icon or text)
    document.addEventListener("click",function(e){
        var icon=e.target.closest(".reaper-toc-toggle-icon");
        if(!icon) return;
        var parent=icon.parentElement;
        var sublist=parent.querySelector("ol");
        if(!sublist) return;
        sublist.classList.toggle("collapsed");
        icon.innerHTML=sublist.classList.contains("collapsed")?"\u25B6":"\u25BC";
    });
})
