// =======================================================
// [설정] 본인의 GitHub 정보로 수정하세요.
const CONFIG = {
    owner: 'betapa',      // 예: gildong
    repo: 'sdvx_total',   // 예: sdvx-data
    path: 'sdvx_playdata.csv' // 저장할 파일명
};
// =======================================================

(async function() {
    // 0. 토큰 확인
    let token = localStorage.getItem('GH_TOKEN');
    if (!token) {
        token = prompt("GitHub Personal Access Token을 입력해주세요.\n(repo 권한 필요)");
        if (!token) return alert("토큰이 없어 취소합니다.");
        localStorage.setItem('GH_TOKEN', token);
    }

    const UI = {
        log: (msg) => console.log(`%c[SDVX] ${msg}`, 'color: cyan'),
        alert: (msg) => alert(`[SDVX Helper]\n${msg}`)
    };

    // 난이도 매핑
    const diffMap = { 'novice': 'NOV', 'advanced': 'ADV', 'exhaust': 'EXH', 'maximum': 'MXM', 'infinite': 'INF', 'ultimate': 'ULT' };

    // HTML 텍스트에서 데이터를 추출하는 함수
    const parseRecords = (htmlText) => {
        const doc = new DOMParser().parseFromString(htmlText, 'text/html');
        const rows = doc.querySelectorAll('tr.data_col');
        const pageData = [];

        if (rows.length === 0) return []; // 데이터가 없음

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
                    if (scoreText === '0' || scoreText === '') continue; // 플레이 기록 없음

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

    try {
        UI.log("데이터 수집을 시작합니다...");
        
        let allRecords = [];
        let page = 1;
        let keepGoing = true;
        const limit = 150; // 한 페이지당 최대 곡 수 (설정값)

        // 1. 무한 루프로 페이지 순회 (데이터가 없을 때까지)
        while (keepGoing) {
            UI.log(`${page} 페이지 읽는 중...`);
            document.title = `[${page} page] 수집 중...`;

            const url = `https://p.eagate.573.jp/game/sdvx/vii/playdata/musicdata/index.html?limit=${limit}&sort=0&page=${page}`;
            const res = await fetch(url);
            
            if (!res.ok) {
                UI.log(`페이지 로드 실패 (HTTP ${res.status})`);
                break;
            }

            const htmlText = await res.text();
            
            // 로그인 세션 체크
            if(htmlText.includes("login_form") || htmlText.includes("basic_course")) {
                UI.alert("로그인이 풀렸거나 베이직 코스 가입이 필요합니다.");
                return;
            }

            const pageData = parseRecords(htmlText);

            if (pageData.length === 0) {
                UI.log(`📌 ${page} 페이지에서 데이터가 발견되지 않았습니다. 수집을 종료합니다.`);
                keepGoing = false;
            } else {
                UI.log(`  -> ${pageData.length}개 기록 추출 완료`);
                allRecords.push(...pageData);
                page++;
                
                // 안전장치: 너무 많이 도는 것 방지 (예: 50페이지=7500곡)
                if (page > 50) {
                    UI.log("안전장치 발동: 50페이지 초과로 종료합니다.");
                    keepGoing = false;
                }

                // 서버 부하 방지 대기 (0.5초)
                await new Promise(r => setTimeout(r, 500));
            }
        }

        if (allRecords.length === 0) {
            return UI.alert("수집된 데이터가 없습니다. 페이지가 올바르게 로드되었는지 확인해주세요.");
        }

        // 2. CSV 생성
        let csvContent = "Title,Artist,Difficulty,Score,Grade,Lamp\n";
        allRecords.forEach(r => {
            const escape = (txt) => `"${String(txt).replace(/"/g, '""')}"`;
            csvContent += `${escape(r.Title)},${escape(r.Artist)},${escape(r.Difficulty)},${escape(r.Score)},${escape(r.Grade)},${escape(r.Lamp)}\n`;
        });

        // 3. GitHub API로 업로드
        UI.log(`총 ${allRecords.length}개의 데이터를 GitHub로 전송합니다...`);
        const apiUrl = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${CONFIG.path}`;
        
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
                message: `Update play data (${allRecords.length} records) - ${new Date().toLocaleDateString()}`,
                content: contentBase64,
                sha: sha ? sha : undefined
            })
        });

        if (putRes.ok) {
            UI.alert(`✅ 성공! 총 ${allRecords.length}곡 업데이트 완료.\n(마지막 페이지: ${page-1})`);
            document.title = "업데이트 완료";
        } else {
            const errTxt = await putRes.text();
            UI.alert(`❌ 업로드 실패: ${putRes.status}\n${errTxt}`);
        }

    } catch (err) {
        UI.alert(`오류 발생: ${err}`);
        console.error(err);
    }
})();