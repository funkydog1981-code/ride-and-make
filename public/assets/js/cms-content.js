
(()=>{
const esc=(v)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const breaks=(v)=>esc(v).replace(/\r?\n/g,'<br>');
const set=(sel,v,asBreaks=false)=>{
  const e=document.querySelector(sel);
  if(e)e.innerHTML=asBreaks?breaks(v):esc(v).replace(/\r?\n/g,'<br>');
};
const dateLabel=(v)=>{
  if(!v)return '';
  const d=new Date(v);
  return isNaN(d)?v:`${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}`;
};
const getSlug=()=>{
  const q=new URLSearchParams(location.search).get('slug');
  if(q)return q;
  const m=location.pathname.match(/\/journeys\/([^/]+)\/?$/);
  return m?m[1]:'beppu';
};
const safeMarkdown=(s)=>{
  if(!window.marked)return esc(s).replace(/\n/g,'<br>');
  const raw=window.marked.parse(s||'');
  return window.DOMPurify
    ?DOMPurify.sanitize(raw,{
      ADD_TAGS:['video','source','iframe'],
      ADD_ATTR:['controls','muted','playsinline','preload','poster','src','type','allow','allowfullscreen','frameborder']
    })
    :raw;
};

// 記事内の画像・表が画面からはみ出さないようにする
function fixArticleImages(article){
  if(!article)return;

  article.querySelectorAll('img').forEach(img=>{
    img.style.maxWidth='100%';
    img.style.height='auto';
    img.style.width='auto';
    img.style.display='block';
    img.style.objectFit='contain';
    img.style.margin='24px auto';
  });

  article.querySelectorAll('table').forEach(table=>{
    table.style.maxWidth='100%';
    table.style.width='100%';
    table.style.display='block';
    table.style.overflowX='auto';
  });

  article.querySelectorAll('video,iframe').forEach(media=>{
    media.style.maxWidth='100%';
    media.style.height='auto';
  });
}

async function load(){
  let data;

  try{
    const r=await fetch('/content/site.json',{cache:'no-store'});
    if(!r.ok)throw Error('content missing');
    data=await r.json();
  }catch(e){
    return;
  }

  const hero=data.hero||{};

  // トップページ
  if(document.body.id==='top'||document.querySelector('#journeys')){
    set('.hero-copy .eyebrow',hero.eyebrow);
    set('.hero-copy h1',hero.title,true);
    set('.hero-copy p',hero.description,true);

    const heroButton=document.querySelector('.hero-copy .button');
    if(heroButton){
      heroButton.innerHTML=esc(hero.button_label)+' <span aria-hidden="true">↘</span>';
    }

    set('.hero-caption',hero.caption);

    const hi=document.querySelector('.hero-image img');
    if(hi){
      hi.src=hero.image||hi.src;
      hi.alt=hero.image_alt||'';
      hi.style.maxWidth='100%';
      hi.style.height='auto';
    }

    const js=data.journey_section||{};
    set('#journeys .section-head .eyebrow',js.eyebrow);
    set('#journeys .section-head h2',js.title);
    set('#journeys .section-head p',js.description);

    const journeys=data.journeys||[];
    const j=journeys[0];
    const feature=document.querySelector('#journeys .feature');

    if(j&&feature){
      feature.href='/journeys/'+encodeURIComponent(j.slug)+'/';

      const im=feature.querySelector('.feature-photo img');
      if(im){
        im.src=j.image||'';
        im.alt=j.image_alt||'';
        im.style.maxWidth='100%';
        im.style.height='auto';
      }

      const cp=feature.querySelector('.feature-copy');
      if(cp){
        const pill=cp.querySelector('.pill');
        if(pill)pill.textContent=j.category||'';

        const h3=cp.querySelector('h3');
        if(h3)h3.innerHTML=breaks(j.title||'');

        const p=cp.querySelector('p');
        if(p)p.textContent=j.summary||'';

        const metas=cp.querySelectorAll('.meta b');
        if(metas[0])metas[0].textContent=j.distance||'—';
        if(metas[1])metas[1].textContent=j.ascent||'—';
        if(metas[2])metas[2].textContent=j.period||dateLabel(j.date);
      }
    }

    const latest=document.querySelector('#journeys .latest');
    if(latest){
      latest.innerHTML='<span>記事一覧</span>'+
        journeys.map(x=>`<a href="/journeys/${encodeURIComponent(x.slug)}/">${esc(x.title)}　→</a>`).join('');
    }

    // 道具とものづくり
    const making=data.making||{};
    set('#making .wrap > div:first-child .eyebrow',making.eyebrow);
    set('#making .wrap > div:first-child h2',making.title,true);

    const intro=document.querySelector('#making .wrap > div:first-child');
    if(intro){
      const old=[...intro.querySelectorAll('p')];

      (making.intro_paragraphs||[]).forEach((p,i)=>{
        if(old[i])old[i].innerHTML=breaks(p);
      });

      for(let i=(making.intro_paragraphs||[]).length;i<old.length;i++){
        old[i].remove();
      }
    }

    const projWrap=document.querySelector('#making .wrap > .project-list');
    if(projWrap){
      projWrap.innerHTML=(making.projects||[]).map(p=>
        `<div class="project">
          <span class="status">${esc(p.status)}</span>
          <h3>${breaks(p.title)}</h3>
          <p>${esc(p.description)}</p>
          <details class="project-details">
            <summary>${esc(p.details_summary)}</summary>
            <p>${esc(p.details)}</p>
          </details>
        </div>`
      ).join('');
    }

    // 愛車と装備
    const gear=data.gear||{};
    set('#gear .eyebrow',gear.eyebrow);
    set('#gear h2',gear.title,true);
    set('#gear > div p',gear.description);

    const gi=document.querySelector('#gear .gear-photo img');
    if(gi){
      gi.src=gear.image||gi.src;
      gi.alt=gear.image_alt||'';
      gi.style.maxWidth='100%';
      gi.style.height='auto';
    }

    const gl=document.querySelector('#gear .gear-list');
    if(gl){
      gl.innerHTML=(gear.items||[]).map(i=>
        `<div><b>${esc(i.label)}</b><span>${esc(i.value)}</span></div>`
      ).join('');
    }

    // このサイトについて
    const about=data.about||{};
    set('#about .eyebrow',about.eyebrow);
    set('#about h2',about.title,true);

    const exp=document.querySelector('#about .experience');
    if(exp){
      exp.innerHTML=(about.experience||[]).map(i=>
        `<div><strong>${esc(i.value)}</strong><small>${esc(i.label)}</small></div>`
      ).join('');
    }

    const aboutText=document.querySelector('#about .about-inner > div:nth-child(2)');
    if(aboutText){
      aboutText.innerHTML=(about.paragraphs||[]).map(p=>
        `<p>${esc(p)}</p>`
      ).join('');
    }
  }

  // 記事ページ
  const article=document.querySelector('#article-body');

  if(article){
    const slug=getSlug();
    const item=(data.journeys||[]).find(x=>x.slug===slug);

    if(!item){
      article.innerHTML='<p>記事が見つかりません。管理画面で記事のURL用IDを確認してください。</p>';
      return;
    }

    document.title=`${item.title}｜走って、つくって。`;

    const meta=document.querySelector('meta[name="description"]');
    if(meta)meta.content=item.summary||'';

    const img=document.querySelector('.hero > img');
    if(img){
      img.src=item.hero_image||item.image||hero.image;
      img.alt=item.image_alt||'';
      img.style.maxWidth='100%';
      img.style.height='auto';
    }

    const tag=document.querySelector('.hero-copy .tag');
    if(tag)tag.textContent=item.category||'';

    const h=document.querySelector('.hero-copy h1');
    if(h)h.innerHTML=breaks(item.title||'');

    const hp=document.querySelector('.hero-copy p');
    if(hp)hp.textContent=item.summary||'';

    const intro=document.querySelector('.intro');
    if(intro){
      const h2=intro.querySelector('h2');
      if(h2)h2.innerHTML=breaks(item.intro_title||item.title);

      const p=intro.querySelector('p');
      if(p)p.textContent=item.intro||item.summary;

      const facts=intro.querySelectorAll('.facts strong');
      if(facts[0])facts[0].textContent=item.distance||'—';
      if(facts[1])facts[1].textContent=item.ascent||'—';
      if(facts[2])facts[2].textContent=dateLabel(item.date);
    }

    // 記事本文を表示してから、画像・表のサイズを調整
    article.innerHTML=safeMarkdown(item.body||'');
    fixArticleImages(article);

    // 記事内の目次を作成
    const toc=document.querySelector('.toc');
    if(toc){
      const heads=[...article.querySelectorAll('h2,h3')];

      toc.innerHTML='<p>IN THIS JOURNAL</p>'+
        heads.map((h,i)=>{
          const id='article-section-'+(i+1);
          h.id=id;
          return `<a href="#${id}">${esc(h.textContent)}</a>`;
        }).join('');
    }
  }
}

if(document.readyState==='loading'){
  document.addEventListener('DOMContentLoaded',load);
}else{
  load();
}
})();
