// =======================================================
// [설정] 
const CONFIG = {
    owner: 'betapa',      // 예: gil-dong
    repo: 'sdvx_total',   // 예: sdvx-data
    path: 'sdvx_playdata.csv' // 저장할 파일명
};
// =======================================================

(async function() {
    // 0. 토큰 확인 (최초 1회만 입력)
    let token = localStorage.getItem('GH_TOKEN');
    if (!token) {
        token = prompt("GitHub Personal Access Token을 입력해주세요.\n(repo 권한 필요, 이 기기에 저장됩니다.)");
        if (!token) return alert("토큰이 없어 취소합니다.");
        localStorage.setItem('GH_TOKEN', token);
    }

    const UI = {
        log: (msg) => console.log(`[SDVX] ${msg}`),
        alert: (msg) => alert(`[SDVX Helper]\n${msg}`)
    };

    try {
        UI.log("데이터 수집을 시작합니다...");
        
        // 1. 페이지 수 확인
        const limit = 150; // 한 페이지당 곡 수
        const firstPageRes = await fetch(`https://p.eagate.573.jp/game/sdvx/vii/playdata/musicdata/index.html?limit=${limit}&sort=0&page=1`);
        const firstPageText = await firstPageRes.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(firstPageText, 'text/html');
        
        // 페이지 수 파싱
        const pageSpan = doc.querySelector('span.page_num');
        // page_num이 "1/3" 형태일 수도 있고 그냥 숫자일 수도 있음. 안전하게 처리
        let maxPage = 1;
        if(pageSpan) {
             const txt = pageSpan.textContent;
             // 뒤의 숫자 추출 (예: 1/15 -> 15)
             const match = txt.match(/\/([0-9]+)/);
             maxPage = match ? parseInt(match[1]) : 1;
        }

        UI.log(`총 ${maxPage} 페이지를 발견했습니다.`);
        
        let allRecords = [];

        // 2. 데이터 파싱 함수
        const parseRecords = (htmlText) => {
            const doc = new DOMParser().parseFromString(htmlText, 'text/html');
            const rows = doc.querySelectorAll('tr.data_col');
            const pageData = [];

            const diffMap = { 'novice': 'NOV', 'advanced': 'ADV', 'exhaust': 'EXH', 'maximum': 'MXM', 'infinite': 'INF', 'ultimate': 'ULT' };

            rows.forEach(row => {
                try {
                    const titleElem = row.querySelector('.music .title a');
                    if (!titleElem) return;
                    const title = titleElem.textContent.trim();
                    
                    const artistElem = row.querySelector('.music .artist');
                    const artist = artistElem ? artistElem.textContent.trim() : "";

                    for (const [cls, label] of Object.entries(diffMap)) {
                        const td = row.querySelector(`td.${cls}`);
                        if (!td) continue;

                        const scoreText = td.textContent.trim();
                        if (scoreText === '0') continue;

                        // 램프 분석
                        let lamp = "PLAYED";
                        const markImg = td.querySelector('img[src*="mark"]');
                        if (markImg) {
                            const src = markImg.src;
                            if (src.includes('mark_no')) continue;
                            if (src.includes('per')) lamp = "PUC";
                            else if (src.includes('uc')) lamp = "UC";
                            else if (src.includes('comp_ex')) lamp = "EXC CLEAR";
                            else if (src.includes('comp')) lamp = "CLEAR";
                            else if (src.includes('play')) lamp = "FAILED";
                        }

                        // 등급 분석
                        let grade = "-";
                        const gradeImg = td.querySelector('img[src*="grade"]');
                        if (gradeImg) {
                            const src = gradeImg.src;
                            if (src.includes('grade_s')) grade = "S";
                            else if (src.includes('aaa_plus')) grade = "AAA+";
                            else if (src.includes('aaa')) grade = "AAA";
                            else if (src.includes('aa_plus')) grade = "AA+";
                            else if (src.includes('aa')) grade = "AA";
                            else if (src.includes('a_plus')) grade = "A+";
                            else if (src.includes('a')) grade = "A";
                            else if (src.includes('b')) grade = "B";
                            else if (src.includes('c')) grade = "C";
                            else if (src.includes('d')) grade = "D";
                        }

                        pageData.push({ Title: title, Artist: artist, Difficulty: label, Score: scoreText, Grade: grade, Lamp: lamp });
                    }
                } catch (e) { console.error(e); }
            });
            return pageData;
        };

        // 3. 페이지 순회
        for (let i = 1; i <= maxPage; i++) {
            UI.log(`${i}/${maxPage} 페이지 수집 중...`);
            // UI 피드백을 위해 title 변경
            document.title = `[${i}/${maxPage}] 수집 중...`;

            let html = "";
            if (i === 1) html = firstPageText;
            else {
                const res = await fetch(`https://p.eagate.573.jp/game/sdvx/vii/playdata/musicdata/index.html?limit=${limit}&sort=0&page=${i}`);
                html = await res.text();
            }
            
            const pData = parseRecords(html);
            allRecords.push(...pData);
            
            // 서버 부하 방지를 위한 짧은 대기 (0.5초)
            await new Promise(r => setTimeout(r, 500));
        }

        // 4. CSV 생성
        let csvContent = "Title,Artist,Difficulty,Score,Grade,Lamp\n";
        allRecords.forEach(r => {
            // CSV 이스케이프 처리 (제목에 콤마가 있을 경우 등)
            const escape = (txt) => `"${String(txt).replace(/"/g, '""')}"`;
            csvContent += `${escape(r.Title)},${escape(r.Artist)},${escape(r.Difficulty)},${escape(r.Score)},${escape(r.Grade)},${escape(r.Lamp)}\n`;
        });

        // 5. GitHub API로 업로드 (PUT /repos/:owner/:repo/contents/:path)
        UI.log("GitHub에 업로드 중...");
        const apiUrl = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${CONFIG.path}`;
        
        // 기존 파일의 SHA 값을 가져와야 덮어쓰기가 가능함
        let sha = "";
        try {
            const getRes = await fetch(apiUrl, {
                headers: { 'Authorization': `token ${token}` }
            });
            if (getRes.ok) {
                const getData = await getRes.json();
                sha = getData.sha;
            }
        } catch(e) {}

        // Base64 인코딩 (한글 깨짐 방지 위해 UTF-8 처리 중요)
        const utf8Encoder = new TextEncoder();
        const csvBytes = utf8Encoder.encode(csvContent);
        let binaryString = "";
        csvBytes.forEach(byte => binaryString += String.fromCharCode(byte));
        const contentBase64 = btoa(binaryString);

        const putRes = await fetch(apiUrl, {
            method: 'PUT',
            headers: {
                'Authorization': `token ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                message: `Update play data via Bookmarklet (${new Date().toLocaleDateString()})`,
                content: contentBase64,
                sha: sha ? sha : undefined
            })
        });

        if (putRes.ok) {
            UI.alert(`성공! 총 ${allRecords.length}곡의 기록이 업데이트되었습니다.`);
            document.title = "완료!";
        } else {
            const errTxt = await putRes.text();
            UI.alert(`업로드 실패: ${putRes.status}\n${errTxt}`);
        }

    } catch (err) {
        UI.alert(`오류 발생: ${err}`);
        console.error(err);
    }
})();