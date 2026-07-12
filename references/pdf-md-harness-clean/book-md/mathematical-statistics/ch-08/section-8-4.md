# 8.4 추정량의 점근적 비교

> OCR engine: macOS Vision (`ko-KR,en-US`)
> Original PDF pages: 349-366

<!-- page 349 -->

추정량의 점근적 비교

표본크기가 커짐에 따라 추정값이 추정 대상의 참값에 가까워지는 일치성을 가진 추정량들을 비교하는 경우에 그 극한분포의 산포가 작을수록 추정 오차가 작은 것을 뜻하므로 일치추정량의 비교 기준으로서 극한분포의 분산을 흔히 사용한다.120) 이 절 에서는 이와 같은 극한분포의 분산을 이용한 추정량의 비교에 대하여 알아본다.

## 120) 크기 n인 표본에 기초한 추정량의 평균제곱오차는

MSE(7,0)=E.(77(0)21=Varo(7)+lE,(7)-710)3 와 같이 추정량의 분산 Varo(7,)과 치우침 또는 편의(1)(), bias)라고 불리우는 Biaso(Th)=Eo(72)-71(8) 의 제곱의 합으로 주어진다. 그런데 많은 일치추정량에 대하여 편의의 제곱 [Biaso (7,)12 은 2의 속도로 0에 가까워지고 분산 Varo(7)은 n'의 속도로 0에 가까워지므로, 표 본크기가 커질 때 추정량을 비교하는 경우에는 극한분포의 분산을 비교 기준으로 하는 것이다. 362 8장 추정량의 비교

<!-- page 350 -->

예 8.4.1 로지스틱분포에서의 추정량 비교 로지스틱분포 L (0,1), - 8< 0<+∞에서 0는 모집단의 중앙값이며 평균이 기도 하다. 따라서 랜덤표본 XI, , X,을 이용하는 0의 추정량으로는 표본중 앙값121) 6fped = X (+ 1/2) , 표본평균 6.com=X 또는 예 6.4.23의 최대 가능도추정량 0m, 을 생각할 수 있다. 한편 예 4.1.5>에 주어진 로지스틱분포의 확률밀도함수와 예 5.3.8~에 주어진 표본분위수의 극한분포에 대한 결과로부터 '-0) -> N(0,4) 이고, 중심극한정리와 < 5.4.3>에 주어진 로지스틱분포의 분산으로부터 vn(6.; mn ean

## 0) - N(0,72/3)

72->8 또한 <예 6.4.4>에 주어진 최대가능도추정량의 극한분포로부터

## (MLE-0)- N(0,3)

## 22X8

따라서 표본크기가 충분히 커지는 경우에 극한분포의 분산이 작은 순서대로 효율 성이 좋은 순서는 최대가능도추정량, 표본평균, 표본중앙값의 순서이다. 점근상대효율성: 두 추정량 6,,6,에 대하여 Va(8,'-0) - N(0,0(0)) (i=1,2) 와 같은 점근정규성이 성립할 때, 그 극한분포의 분산의 역수의 비인 o72(0)/022(0) 을 추정량 6,의 6에 대한 점근상대효율성(해도 차)) 주시보, asympiotic relative efficiency)이라고 하며 기호로는 다음과 같이 나타낸다. ARD(6),(02)=920)1072(8) 이와 같은 점근상대효율성의 값이 커진다는 것은 표본크기가 커지면서 추정의 정밀도가 상대적으로 높아지는 것을 뜻하며, 따라서 상대적으로 추정의 정밀도가 더

## 121) 여기에서 [(n+1)/2]는 (n+1)/2 이하의 가장 큰 자연수를 뜻한다. 즉 표본크기가 큰

경우에 표본중앙값은 n= 2m이면 X(m), n=2m+1이면 X(m+1)로 하기로 한다.

<!-- page 351 -->

좋은 추정방법은 더 적은 표본크기로도 요구되는 추정오차한계를 만족시킬 수 있음 을 뜻한다. 예 8.4.2 로지스틱분포에서 추정오차한계와 점근상대효율성 로지스틱분포 L(0,1), -∞< 0<+∞에서 표본중앙값을 이용하여 0에 관한 95% 점근신뢰구간을 구하면 다음과 같이 주어지는 것을 <예 8.4.1>로부터 알 수 있다. 0E[6.mca- 1.96 vA/, 6,cl + 1.96~4/m] 이 때 추정값과 추정대상의 차이의 한계를 나타내는 1.96 y 4/m 을 표본중앙값의 95% 점근추정오차한계라고 한다. 따라서 표본중앙값을 이용하여 95% 점근추정오 차한계를 d 이하로 하기 위하여 요구되는 표본의 크기를 7imed 라고 하면 pmed= (1.96/d)24 마찬가지로 표본평균을 이용하여 추정하는 경우에 같은 오차한계를 달성하기 위 한 표본의 크기를 Pneun 이라고 하면 Pmean= (1.96/d):72/3 따라서 이들 표본크기의 역수의 비는 Pintennit = 12/32 는 1.2= ARE(Omeon , fe.mcal) 즉 표본평균의 추정 정밀도가 표본중앙값에 비하여 약 1.2배이므로 표본중앙값을 이용하면 약 1.2배의 표본 개수가 필요하게 되어 효율성이 상대적으로 떨어진다 는 뜻이다. 예 8.4.3 위치모수 모형에서 중앙값의 추정 <예 8.4.12에서와 같이 모집단 분포가 연속형이고 확률밀도함수가 f(2- 0), -∞<0<+∞의 꼴로서 0에 관하여 대칭인 경우, 즉 9(2)=J(2) Va: 8CaCt8 인 모형을 생각해보자. 이러한 경우에 랜덤표본 X1,···, X,을 이용한 0의 추 정량으로서 표본중앙값 6fmed =X((a+1)/2)의 경우에는 예 5.3.72의 결과로 부터 그 극한분포가 364 8장 추정량의 비교

<!-- page 352 -->

로 주어지고, 표본평균 0.7ean = X의 경우에는 모분산이 존재한다는 조건 하에 서, 즉 +8 -∞ 2:f(2) de <+∞ 라는 조건 하에서 그 극한분포가 다음과 같이 주어진다. ✓=(6,men-0), 그 N(0.07) 7->∞ 한편 최대가능도추정량의 경우에는 <정리 6.4.4>의 조건들이 만족된다면 정보 량이 로 주어지므로 이러한 정보량이 양의 실수라는 조건 하에서 그 극한분포는 다음 과 같다. -0) _ , N(0,5 1), 4=/ 1(2)) Ple)dz 이러한 극한분포들의 분산을 모집단 분포에 따라 정리하면 <표 8.4.1>과 같이 주어지고, 이로부터 각 추정방법 간의 점근상대효율성을 정리하면 <표 8.4.2>와 같다. 표 8.4.1 표본중앙값, 표본평균, 최대가능도추정량의 극한분포의 분산 모집단 분포

## N(0,1)

## L(0,1)

## DE(0,1)

(4p2(0)-1 ㅠ/2 5! 표 8.4.2 표본중앙값, 표본평균, 최대가능도추정량 간의 근상대효율성 모집단 분포

## N(0,1)

## L(0,1)

## DE(0,1)

## ARE(B, EC,

"/2 12/72 1/2 9/72 1/2

## ARE (OTC G, ME)

3/4

<!-- page 353 -->

예 8.4.4 베타분포 모형 B eta(a,1), o> 0에서 추정량의 비교 베타분포 Beta(a,1), a> 0의 확률밀도함수는 J(t;a)=029-'1o.1)(z) 이고 모평균이 21=a/(a+1)이므로 랜덤표본 Xr,···,X,을 이용한 a의 적 률이용추정량은 an

## ^ MME

1-m1

## 1-X

로 주어지고, 그 극한분포는 <정리 6.1.2>로부터 다음과 같이 주어진다. a+2 한편 이 모형의 확률밀도함수는 f(tia)=aza-'10.1(2)=exp((a-1)10g2+10gatlo.1)(2) 와 같이 나타내어지는 지수족의 경우로서 <정리 6.2.4>의 조건을 만족시키므로 a의 최대가능도추정량은 가능도방정식 2= 1 2108x.+"=0 의 근으로 주어진다. 즉 a의 최대가능도추정량은 로 주어지고, 그 극한분포는 중심극한정리 또는 <정리 6.4.4~로부터 다음과 같이 주어진다. 즉 vi(MiE-a) SN(0.02) 따라서 적률이용추정량의 최대가능도추정량에 대한 점근상대효율성은 1RE(aue,(e.ve)= alat)? a+2 1a-2= 0(a+2) (a+1): 로 주어지고, 이로부터 최대가능도추정량이 적률이용추정량에 비하여 점근적으로 더 효율적임을 알 수 있다 366 8장 추정량의 비교

<!-- page 354 -->

이제까지의 예에서 점근상대효율성이 가장 큰 추정량은 최대가능도추정량이었다. 이와 같은 최대가능도추정량의 점근적 효율성은 다음의 정보량 부등식으로부터 추측될 수도 있다. 정리 8.4.1 정보량 부등식122)(information inequality) 확률밀도함수가 J(a:0), 0E 2인 확률모형에서 최대가능도추정량의 점근 정규성 을 위한 기본 조건인 <정리 6.4.3>에서의 조건 (RO)~ (R5)가 만족된다 고 하자. 이 때 랜덤표본 X 1, , X,,을 이용한 실수 값 모수123) 17= 7(0)의 추정량 7= 7(X ,,·•X.)의 분산에 대하여 다음 부등식이 성립한다. varo(n)=(DEo(Th) ho) 0Po(hi), OED [증명] 첫째로 모수 0가 일차원인 경우의 증명에 대하여 생각해보자. 이 경우에 점수합수 1(0)= 0E7108 (31.0)와 추정량 17ih=i.(5.2.)의 공 분산과 분산에 대하여 코쉬슈바르츠 부등식 Varo(T)Varo((0)≥ {Cor(Thi,(0)? 이 성립함을 알고 있다. 한편 <정리 6.4.3>으로부터 주어진 조건 하에서

## 임을 알 수 있고, 조건 (R4)로부터 다음이 성립한다.

따라서 위의 코쉬슈바르츠 부등식에 이를 대입하면 부등식 Vari)=(oEo(t) 1no), roED

## 122) 이 부등식을 크라메-라오(Cramer-Rao) 부등식이라고도 한다

123) 77=m(0)가 다차원의 모수, 즉 벡터인 경우에는 같은 방법으로

와 같은 부등식이 성립하는 것을 알 수 있다.

<!-- page 355 -->

이 성립하게 되어 모수 0가 일차원인 경우에 정보량 부등식을 얻게 된다. 모수 0가 다차원인 경우에는 011= Varo(7), 212=Cov(i,(0), 522= Varo(i,(0), 521= Covi,(0), 7h) 라고 하면 일차원인 경우와 마찬가지로 임을 알 수 있다. 한편 011-2122521=Var(-5122)(0)20,VOER 이므로 부등식 이 성립하는 것을 알 수 있다. 정리 8.4.2 불편추정량에 대한 정보량 부등식 <정리 8.4.1>의 가정 하에서 0= (0,•·• 9x)'의 불편추정량 6,""에 대하여 다음 이 성립한다. dvarourezer-10)eln, 0eD,ve 즉 0가 일차원 모수인 경우에는 Varo(oncE) ≥ 1/n(0) 이고, 0가 다차원 모수인 경우에는 행렬 Varo(6,'e)-1-10)/m 가 음이 아닌 정부호의 행렬인 것을 뜻한다. [증명] 7=eU=C,0,+··+C0x인 경우에 불편추정량 ThCE= Ce,C에 대하여 cVaroloct)e= Vao(co,u), apole6,)=d 이므로 <정리 84.1의 부등식을 7=c0의 불편추정량 7ACE=d6,4에 적 용한 결과이다. 368 8장 추정량의 비교

<!-- page 356 -->

예 8.4.5 베타분포 모형 Beta(a,1), a> 0에서의 불편추정과 정보량 부등식 베타분포 Beta(a,1), a> 0의 확률밀도함수는 J(a;a)=029-(0.1)(a)=exp{(a-1)10g2+10ga}[(o.1)(z) 로 나타내어지고 이는 지수족에 속하는 경우로서 <정리 8.3.2>의 조건을 만족 시키므로 랜덤표본 X1, , X, (n≥ 3)을 이용한 통계량 Y= 210gXi 8= 1 는 a> 0에 관한 완비충분통계량이다. 한편 x9U(0,1) (i=1,2) 이므로 따라서 =Q2/1(p-1):(n-2)}, (n ≥ 3) 그러므로 <정리 8.3.1>로부터 a의 전역최소분산불편주정량은 로 주어지고 그 분산은 Var(a,(WtUr)=02/(n-2) 로서 <정리 8.4.2>에서 주어진 정보량 부등식의 하한인 1/nI(a)] = a/n보다 크지만 점근적으로는 같아지는 것을 알 수 있다. 즉 lim Vara (an 72-300 0,616)/(ni(a)1= 1 또한 <예 8.4.4>로부터 an SUNTUE= 2-1 MIE -Um

<!-- page 357 -->

임을 알 수 있고, 최소분산불편추정량은 최대가능도추정량과 같은 극한분포를 갖는다. 즉 va(ancater-a) N(0,22) 이고 두 추정량은 점근적으로 같은 효율성을 갖는다. <정리 8.4.2>로부터 일차원 모수의 경우에 varova(@Ue-0)}≥ 1/1(6) 임을 알 수 있고, 이로부터 vi(6,-0),-N(0,02(0)) 72-280 와 같이 점근정규성을 갖는 추정량의 극한분포의 분산에 대하여 92(0)≥ 1/1(8) 일 것이라는 추측을 할 수 있다. 한편 <정리 6.4.4>로부터 최대가능도추정량의 경 우에 vn(6,115-8) 12-> 00

## 4N(0.17(0)

이 성립하므로 점근정규성을 갖는 추정량 중에서 최대가능도추정량이 최소의 극한분 포 분산을 갖는 것이라고 추측할 수 있다. 이러한 추측을 핏셔의 추측(Fishers conjecture)이라고 하며, 이러한 추측이 일반적 으로는 성립하지 않으나 추가적인 균등수렴(1) 쏙: kAk, uniform convergence)의 조건 하에서는 성립하는 것이 알려져 있다.124) 이러한 뜻에서 최대가능도추정량을 점근적 으로 효율적인 추정량이라고 하며, 이러한 최대가능도추정량의 점근적 효율성은 다차 원 모수의 함수를 추정하는 경우에도 성립하는 것이 알려져 있다. 예 8.4.6 감마분포 모형 Gamma(a,B), a> 0, 3> 0에서의 추정량 비교 감마분포 Gamma(a,/3)의 확률밀도함수는 f(2;0)= [(a)30 2-le i/31(520), 0=(a,B)

## 124) 이에 대한 상세한 논의는 참고서적 [P. J. Bickel & K. A. Doksum] Mathematical

Statistics p.331~p.332에 주어져 있다. 370 8장 추정량의 비교

<!-- page 358 -->

이고 이는 다중모수 지수족에 속하는 경우로서 <정리 6.4.4>의 조건들이 만족되 는 것이 알려져 있다. 이를 이용하여 <예 6.4.5~에서는 가능도방정식 1,(0)=

- nE(a)- nlogg+n(log3)

-na/ 3+na/82 =0 의 근으로 주어지는 0=(a,B)'의 최대가능도추정량을 일단계 반복법에 의해 근사하는 방법을 소개하고 있다. 여기에서 (10g2)= n 1og 2:, E(a)= 00 1087(a)이며, 일단계 반복법에 의한 추정량 6,= (ain , 13, ,(1))'은 다음 과 같이 정의된다. 82=810)+136201-(60), 6/0)=8.Mne 여기에서 초기 추정량으로 사용되는 적률이용추정량 0,MNE =(an, (B,)'은 연립 방정식 의 근으로 주어지고, <정리 6.1.2>로부터 그 극한분포를 다음과 같이 구할 수 있다. ✓n(6ne-8) CN(0,5(0), 5(B)= (-2(041)8 (24310)82) 20(a+1) -2(a+1)3 한편 이 경우에 정보량 행렬과 그 역행렬은 각각 I(0)= E,[-i(0)|= (I(a) 1/3 1/8 a/821 I-1(0)= aI(a) - 1 2g wia)8) 로 주어지고 일단계 반복법에 의한 추정량 8,= (a,, 6,"') 에 대하여 v2(6,1)-8) NO.1(0) n->∞ 이 성립하며, 최대가능도추정량 6MME = (a,nme.

## 1, B,MANEy'의 극한분포도 이와

같다. 따라서 이 경우에 적률이용추정량의 최대가능도추정량에 대한 점근상대효율성은 ARB({aMs},faaMuEl)= [20(a+1)1-2/[a/(ai(a)-1)13, ARD(6MME),{&,ME)=(2+3/8)8211/(8(a)82/(a8(a)-1)1 로 주어지고, 그 값을 계산하면 25) <표 8.4.3>과 <표 8.4.4>와 같다.

<!-- page 359 -->

표 8.4.3 ARE(famam, (anmas) = 2(a+1)(ay(a)-1) 의 값 a 1/10 1/2 ARE(fa.me. (a,lue) 0.0497 0.2271 0.3876 0.5749 0.7391 0.8798 표 8.4.4 ARE(18,Ms,(8,MP)= (2a+3)(aw(a)-I)의 값 ai(a) a 1/10 1/2 0.3466 0.4203 0.5101 0.6356 0.7628 0.8850 이들 표에서 알 수 있듯이 이 예에서 적률이용추정량은 최대가능도추정량에 비하여 점근적으로 효율성이 낮다. 이러한 현상은 일반적으로 성립하는 것으로서 최대가능도추 정량은 점근적으로 가장 효율적인 추정량임이 알려져 있다.

## 125) I(a), W(a)는 각각 다이감마(digamma), 트라이감마(trigamma) 함수라고 불리우는 함

이용하여 계산한 결과이다. 수로서 각각 로그감마함수의 일차, 이차 도함수이고 위의 표는 패키지 R에 있는 함수를 372 8장 추정량의 비교

<!-- page 360 -->

다변량 정규분포 신뢰십합 치환 계수 회귀계수 고유값 선형회귀모형 정칙행렬 정칙 다변량 정규분포 확률적분변환 중심극한정리 표본회귀계수 단순 설명변수 점근 대수의 법칙 표본적튤 극한분포 점근분포 평균오치 난수 첨예도 균등난수 표본상관계수 분위수 분산안정변환 표본분위수 가능도 추정법 추정 추정량 몬테칼로적분 다중모수 지수족 점수함수 연습문제 가능도방정식 일치성 가능도 합수 적률이용추정량 쿨백-라이블러 괴리도 순오목함수 확률측도 정사영 조건부확률 공리 최소제곱 추정법 홬률 최소제곱 추정량 점근정규성 표본공간 확률밀도함수 랜덤한 실험 확률변수 사전 사후 독립 가산가법성 표학수 평규 기댓간 연속형 이산형 표주퍼차 이상 확률분포 확률질량함수 표주화 8.1 베르누이분포 • Bernoulli(p), 0≤ pS 1에서의 랜덤표본 X1,

## X,,을 이용

한 두 추정량 Vn 1tvn ^(0) 1tvn 2 을 비교하려고 한다. (a) 최대평균제곱오차 .."즈 B, (-D))를 기준으로 두 추정량을 비교하여라. (b) 다음의 베이지안평균제곱오차를 기준으로 두 추정량을 비교하여라. /E,(-p))pa1(1-p) 6-140 (c) 평균제곱오차 E, (p-p)]를 기준으로 7/"이 0보다 좋기 위한 p의 범위를 구하여라.

## 8.2 다음 각 모형에서의 랜덤표본을 X1, , X, 이라고 할 때, 8ED에 관한 충

분통계량을 구하여라. (a) Beta(1,0), 0EQ, 2=(0,+∞) (b) Beta(0,0), 0ED, 2=(0,+∞) 8.3 다변량 정규분포 Nx(2), MER, det (2)> 0에서의 랜덤표본을 X 1, ···, 2,이라고 할 때 (, 2)에 관한 충분통계량을 구하여라. 8.4 다음 각 모형에서의 랜덤표본을 X 1; ••·, X,, 이라고 할 때, 0=(1,0)'ED에 관한 충분통계량을 구하여라. (a) 로지스틱분포 L(w,0), - 8<K<+0,0≥0 (6) 코쉬분포 C(0), -8 CA<+0,0≥0

<!-- page 361 -->

## 8.5 실수 전체의 집합에서의 연속형 분포를 모형으로 하는 경우에는 모수공간을

2={f: f는 수직선 위의 연속형 확률밀도함수} 로 나타낼 수 있다. 이러한 모형에서의 랜덤표본을 X 1, , X,, 이라고 할 때

## JED에 관한 충분통계량을 구하여라.

## 8.6 자연수 전체의 집합에서의 이산형 분포를 모형으로 하는 경우에는 모수공

간을 로 나타낼 수 있다. 이러한 모형에서의 랜덤표본을 X1; •·, X,이라고 할 때 (pi,P2,)ED에 관한 충분통계량을 구하여라. 8.7 두 개의 모수를 갖는 지수분포 Exp(4,0), -∞<A<+∞, 0>0에서의 랜덤표본을 관측할 수 없고 이들의 순서통계량 중에서 X(1) <··•<X(주) (1≤ r<n)만을 관측할 수 있다고 한다. 이 때 (w,a)'ERXR.에 관한 충 분통계량을 구하여라. 8.8 균등분포 U-0,0, 0> 0에서의 랜덤표본을 X 1, ••·, X, 이라고 할 때 다음 에 답하여라. (a) Y= 107223J가 BE(0,+∞0)에 관한 충분통계량임을 밝혀라 (b) 랜덤표본의 순서통계량을 X(1) <•••< X(n) (n≥ 2)이라고 할 때, 8=C, (X(m)-X()

## 이 0의 불편추정량이 되기 위한 C,의 값을 구하여라.

(c) (a)에서의 충분통계량 Y=722, X. (22 2)에 기초한 추정량으로서 (1) 에서의 불편추정량보다 더 작은 평균제곱오차를 갖는 추정량을 구하여라. 8.9 기하분포 Geo(p), 0<p< 1에서의 랜덤표본을 X1, , X,, (n≥ 2)이라고 할 때, pE(0,1)에 관한 완비충분통계량과 7의 전역최소분산불편추정량을 구하여라. 374 8장 추정량의 비교

<!-- page 362 -->

## 8.10 확률밀도함수가

J(a:t)=e(-wt.o) (2) 로 주어지는 지수분포 EXp(4,1), -∞<K<+∞에서의 랜덤표본을

## X 1;,X,이라고 할 때, NE(-∞,+∞)에 관한 완비충분통계량과 A의 전

역최소분산불편추정량을 구하여라. 8.11 두 개의 모수를 갖는 지수분포 Exp(4,0), - 8<A<+∞, 0≥ 0에서의 랜덤표본을 X1,•·, X, (n≥ 2)이라고 할 때 다음에 답하여라. (a) (A,o)'ERXR, 에 관한 완비충분통계량을 구하여라. (b) A의 전역최소분산불편추정량을 구하여라. (c) o의 전역최소분산불편추정량을 구하여라.

## 8.12 연습문제 (8.8)에서 다음에 답하여라.

(a) S=( min Airlsisn 1Sism , max X:)'가 BE(0, +∞)에 관한 완비통계량이 아님을 밝혀라. (6) Y=, max IX; 가 9E(0, +∞)에 관한 완비충분통계량임을 밝히고, 0의 전역최소분산불편추정량을 구하여라. 8.13 균등분포 UI-8,201, 0> 0에서 랜덤표본을 X 1, ••, X, 이라고 할 때 다음 에 답하여라. (a) BE(0, +∞)에 관한 최소충분통계량을 구하여라. (b) 0의 전역최소분산불편추정량을 구하여라.

## 8.14 확률밀도함수가

1(1;0)= 급, Z= 1,0 로 주어지는 이산균등분포 U{1,, }, 0ED, D={1,2,}에서의 랜덤표

## 본을 X1; ., X,,이라고 할 때 다음에 답하여라.

<!-- page 363 -->

(a) Y= max X가 0E2에 관한 완비중분통계량임을 밝혀라. (b) 0의 전역최소분산불편추정량을 구하여라. 8.15 정규분포 N(o2), -∞<K<+∞, 0>0에서의 랜덤표본을 X 1, •, Xm (n≥ 2)이라고 할 때 7=k/의 전역최소분산불편추정량을 구하여라. 8.16 포이송분포 Poisson (8), 0≥ 0에서의 랜덤표본을 X 1, ··, X, 이라고 할 때 7=Po(X, 27) (”은 주어진 자연수) 의 전역최소분산불편추정량을 구하여라. 8.17 정규분포 N(w.o2), -∞<K<+∞, 0> 0에서의 랜덤표본을 X1, …, X,.(n≥ 2)이라고 할 때 7=Po(X,>a) (0=(,0)') 의 전역최소분산불편추정량을 구하여라. 8.18 두 개의 모수를 갖는 지수분포 Exp(a), - 8 CA<+∞, 0> 0에서의 랜덤표본을 X1, , X, (p≥ 2)이라고 할 때 7=Po(X,>a) (0=(1,0)') 의 전역최소분산불편추정량을 구하여라. 8.19 포아송분포 Poisson (0), 0≥ 0에서의 랜덤표본을 X 1, ·•, X,이라고 할 때

## 에 대하여 점근상대효율성 ARE( 6,}, (6,2)을 구하여라.

8.20 정규분포 N(,o2), -∞<K<+∞, 0> 0에서의 랜덤표본을 X1, …, X,,("≥ 2)이라고 할 때 다음에 답하여라. (a) o의 전역최소분산불편추정량 on,UNTUE을 구하여라. 376 8장 추정량의 비교

<!-- page 364 -->

(b) 표본표준편차 S,=

## 2(X-27 (7-1)의 전역회소불편주정량

## ONCNTUE에 대한 점근상대효율성 ARE((S,},(o,CATCE)을 구하여라.

(C) o의 불편추정량 on,CF의 분산에 대한 정보량 부등식을 구하여라. (참고: 점근상대효율성의 계산에서 다음 근사식을 사용한다. 이러한 근사식 은 부록 I의 예 1.3.1>과 <정리 1 .7.1>로부터 밝힐 수 있다.) 1(m+1)=m"+le-"~2m(1+rm), Vmrana.o (1+a/n)"=e"(1+R,), Vnf,-00 8.21 <정리 8.4.1>의 정보량 부등식에서 주어지는 분산의 하한은 모수의 일대일 변환에 무관한 것을 밝혀라. 즉 5=g(0)이고 9가 일대일이고 미분가 능한 함수일 때 8.22 연습문제 (8.15)에서 7=7(0)의 불편추정량 772의 분산에 대한 정보 량 부등식을 구하고, 7=7(0)의 최대가능도추정량 711의 극한분포를 구하여라. 8.23 연습문제 (8.17)에서 a=0인 경우에 7=7(0)의 불편추정량 7,4의 분 산에 대한 정보량 부등식을 구하고, 7= 7(B)의 최대가능도추정량 77.NT.B 의 극한분포를 구하여라.

## 8.24 확률밀도함수가

f(t:0,3)=a3oza-lexp(-29/39)10,+c)(z) 인 와이불분포 Weibull(a,3), a> 0, 3≥ 0 모형에서의 랜덤표본을 X 1, •, X,, 이라고 할 때, <정리 6.4.3>의 조건 (RO)~ (R5)가 만족되는 것을 가정 하고 10gX (i= 1,7)의 적률을 이용한 추정량

<!-- page 365 -->

2= V1.649/Sigs, Sligs = |Z(08x,- Tosx))?

## 의 최대가능도추정량 Q,NLE에 대한 점근상대효율성을 구하여라.

8.25 <예 8.3.82과 <예 8.3.102에서 7= 7(0)의 최대가능도추정량 7.MILE 과

## 전역최소분산불편추정량 7h CHYUE에 대하여

"->∞ 임을 밝히고, Vn(mWTUE-m)의 극한분포를 구하여라. 378 8장 추정량의 비교

<!-- page 366 -->

ability density function) 연속형(continuous type) 이상(w improper) 확률분포(68)fh probability distribution) 지표함수(11 9) nent) 확률변수(제출 3로 random variable) 이산형(BE discrete type) 확률질량함수(제23:5 (3) probability mass fuction) 확률밀도함수 (1. 3) 1) wt cumulative distribution function) 표준지수분포(1877) standard exponential distribution) 멱급수(류 power series) 확률생 inction) 평균(Tt mean) 기댓값(071값 expected value) 표준편차(1부 16% standard deviation) 표준화 (34f standardized) 누적분포함수 wwt cumulant generating function) 누율(# cumulant) 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integral 4wpiw probability generating function) 적률생성함수(후보 8g moment generating function) 적률(분후 moment) 누율생성하 jint) 주변( marginal) 공분산(AA covariance) 상관계수(ABBW ga correlation coefficient) 결합적률(습쪽 joint mon =건부(1%19 conditional) 조건부평균(conditional mean) 조건부기댓값(conditional expected value) 조건부분산 률생성함수(jaint moment generating function) 결합누율생성함수(joint cumulant generating function) 합누율 joint n ctor) 전치(transpose) 평균벡터(mean vector) 분산공분산행렬(variance covariance matrix) 정부호 variance) 회귀함수(B) ww regression function) 평균제곱예측오차(mean squared prediction error) 행벡F) 단분포(##해411 population distribution) 비복원추출(sampling without replace ve definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(F) 4 popul tHE oopulation proportion) 초기하분포(※mAm) hypergeome 랜덤추출 (부\랜덤#W simple random sampling) 랜덤표본(random sampl tion) 복원추출(19 TH H sampling with replacement) 이항분 al definition 다항분포(814rtn multinomial di binomial distribution) 대의적 정의(ftal 2륨 repr 다항계수 (21E 6 wa multinomial coefficie [숲 (※f] 7p geometric distribution) on) 음이항전개식(negative IA t negative binomia xpansion) 포아송(Polss 과정(Poisson process) urrence rate) 정상성

## 1) 독립증분성 (indepe

희귀성(rareness) 지수분 nent) 비례성 (propo htial distribution) 감마분 검정의 비교 parameter) 척도모수(REA distribution) 형상모수(T61차) ormal distribution) 분위수(upper quanti neter) 표준정규분포(류 1L 8857 fi s 비율(1xlt sample proportion) 표본평균(배초주부) (타wwm parameter space) 통계량(WEam sta atistics) 표본중앙값(배+맛값 sample medi an) 표본분포(*9m) san) 표본분산(불추A 및 sample variance listribution) 위치모수(1189k location parameter) 척도모수(RIgg scale ) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(E¥Am uniform distribuu 포(chi-squared distribution) 신뢰수준(1)가# confidence level) 신뢰구간(18a) confidence 포 (=RAm triangular distribution) 야코비안(Jacobian) 자유도(Etl degrees of freedor.. 2류모형 TAl one Way classification model) 신뢰집합(1 probability integral transformation) 다변량 정규분포(3m EMAm multivariate nor. A confidence set) 치환(맵)윗 per: 3념값 characteristic value) 선형회귀모형(89⅜142 linear regression model) 설명변수(explanatory variable) 반응변수 n) 청칙행렬(nons ingular matrix) 정칙 다변량 정규분포(TEW) 3했료 EMAT nonsingular multivarate normal distr 합(푸1)꽃#제곱합 mean squared error sum of squares) 중심극한정리(+)319 central limit theorem) ble) 계수(1월 rank) 회귀계수(BS(w regression coefficient) 표본회귀계수(sample regression coefficient) 극한분포(8분 7 75 limitn 단순(Bwt simple) c

7) 점근분포(wifa mi asymptotic distribution) 대수의 법칙(X%의 표 law of large numbers) 표본적률(sample moment) 분위수(A 111,

표본분위수(1fftw sample quantile coefficient) 분산안정변환(슈퍼 및 슬럿츠키(Slutsky) 근(wfif asymptotic) 첨예도(샷9 kurtosis) 표본상관계수(118W 1K sample 로테칼로적분(Monte Carlo integration) 적률이용추정량(표지)Mitre method of moments estimator(MME)) 추정(111 estimation) 추정량 (1E variance syabilizing transformation) 난수(8lg random number) 균등난수(1)*월. g uniform randon 가능도방정식(미) hat likekihood equation) 순오목함수(strictly concave function) 경계(19 boundary) 다중모수 지수족 (38 1k multi or) 일치성 1 consistency) 가능도 함수(미 HE g likelihood function) 우도(XE) 최대가능도 추정법(가피합 "학 #카: maximum likelihood t exponential family of pdf's) 쿨백-라이블러 괴리도(Kullback-Leibler divergence) 근정규성 (WiF IERft asymptotic normality) 점수함수(score functio dicular projection) 공리(AT axiom) 표본공간(11m sample space) 확률(mw probability) 가산가법성(countable additivity) 확률측도 (783) prob: 문 information number) 최소제곱 추정법(least squares estmation) 최소제곱 추정량(least squares estimator) 열벡터 공간(column space) 정사영(TE) 1험(random experiment) 확률변수(Bf 푸※ 1 random variable) 이산형 (월 discrete type) 확률질량함수(대 후 월로 05w probability mass fuction) 률밀도; Ire) 조건부확률(19119 6f conditional probability) 사전(폴l prior) 사후(54% posterior) 독립(3] mutually independent) 종속(618 mutually depende nction) 평균(푸 mean) 기댓값(19#값 expected value) 표준편차(1부(초 standard deviation) 표준화(1류*ft standardized) 누적분포함수(91Eig 25w probability density function) 연속형(표 continuous type) 이상(ix improper) 확률분포(3부5) probability distribution) 지표함수() 5 tribution function) 표준지수분포(2) th standard exponential distribution) 멱급수(#e power series) 확률생성함수(1%1mw probability gf ction) 적률생성함수(푸또#Bg moment generating function) 적률(#후 moment) 누율생성함수(우산#g cumulant generating function) 누율(복 n coefficient) 결합적률(볶슴#※ joint moment) 결합적률생성함수(joint moment generating function) 결합누율생성함수 joint cumulant generating ur 이변량(bivariate) 확률벡터(random vector) 반복적분(iterated integral) 결합(joint) 주변 (B를 marginal) 공분산(IA covariance) 상관계수(NE) 6FE 글(joint cumulant) 조건부(18ftwi conditional) 조건부평균(conaitional mean) 조건부기댓값(conditional expected value) 조건부분산(conditional variand 38류 및 regression function) 평균제곱예측오차(mean squared prediction error) 행벡터(column vector) 전치(transpose) 평균벡터(mean vector) 분산: ariance covariance matrix) 정부호(nonnegative definite) 기울기벡터(gradient vector) 헤시안행렬(Hessian matrix) 모집단(1EE population) 모집단 |율(Rite population proportion) 초기하분포(19Am hypergeometric distribution) 복원추출(1jtiti sampling with replacement) 이항분포 7t population distribution) 비복원추출(sampling without replacement) 단순랜덤추출(1%랜덤 Hts simple random sampling) 랜덤표본(random omial distribution) 대의적 정의(fE Fi representational definition 다항분포(31est multinomial distribution) 다항계수(※ 1E 6Fe multinor Poisson) 포아송 과정(Poisson process) 발생률(occurrence rate) 정상성(stationarity) 독립증분성(independent increment) 비례성(proportiona ent) 기하분포(#Am geometric distribution) 음이항분포(4) mAt negative binomial distribution) 음이항전개식(negative binomial expan 정규분포(※ HAM standard normal distribution) 분위수(upper quantile) 모수공간(타함* parameter space) 통계량(Wate statisti eness) 지수분포(exponential distribution) 감마분포(gamma distribution) 형상모수(THe w shape parameter) 척도모수 :(REAs scale pa *lte sample proportion) 표본평균(주) 2+*값 sample medi an) 표본분포(0기 t sampling distribution) 위치모수(#폴 location parameter) 척도모수(RIE 19분: sample mean) 표본부산(34W sample variance) 순서통계량(MIT% +m order statistic roblan) 자유도(mmit degrees of freedom) 카이제곱분포(chi-squared distribution) 신뢰수준 (1등가* confidence level) 신뢰 r) 이중지수(double exponential) 코쉬(Cauchy) 균등분포(벼쏙Am uniform distribution) 삼각분포(=RAtn triangular distributic confidence interval) 일원분류모형 probability iAer one way classification model) 신뢰집합 (1등부금 confidence set) 치환

7) 정칙행렬 (nons ingular matrix) 정식 다변량 정규분포(TE 3※로 TRA f nonsingular multivariate normal distrih

intearal transformation) 다변량 정규분포(3m FERAm multivariate norn 집값 characteristic value) 선형회귀모형(동포 onse variable) 계수(h1g rank) 회귀계수(미용 4 맞 010r linear recression model) 설명변수(explanatory variable 순(9⅜t simple) 평균오차제곱합(꾸##제급합 mean squared error sum of squares) 중심극한정리(1) rearession coefficient) 표본회귀계수(sample regression cr 칙 (+)의 ta law of Targe numbers) 표본적률(sample moment) 분위수(A(1 quantile) 표본분이 al limit theorem) 극한분포(wee Ah limiting distribution) 점근분포(#iii fth asymptotic distributior th sample quantile) 슬럿츠키(Sutsky) 근 (Fi asymptotic) 첨예도 (329 kurtosis) 표본상
